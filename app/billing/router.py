from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing import stripe_client
from app.billing.models import Subscription
from app.billing.plans import PLANS, entitlements_for
from app.billing.service import price_for, usage
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.users.models import User
from app.workspaces.router import _require_member

router = APIRouter(prefix="/workspaces/{workspace_id}/billing", tags=["Billing"])

# Same-site path only (no scheme, no //host), so Stripe can never send people somewhere else.
RETURN_PATH = r"^/([^/\s\\][^\s\\]*)?$"


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"]
    interval: Literal["month", "year"] = "month"
    return_path: str = Field(default="/projects", pattern=RETURN_PATH, max_length=500)


class PortalRequest(BaseModel):
    return_path: str = Field(default="/projects", pattern=RETURN_PATH, max_length=500)


def _url(path: str, **query: str) -> str:
    joiner = "&" if "?" in path else "?"
    suffix = joiner + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""
    return f"{settings.app_base_url.rstrip('/')}{path}{suffix}"


def _require_owner(session, workspace_id: UUID, user: User):
    member = _require_member(session, workspace_id, user)
    if member.role != "owner":
        raise AppError(403, "FORBIDDEN", "Only the workspace owner can manage billing.")
    return member


def _subscription(session, workspace_id: UUID) -> Subscription:
    sub = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
    if not sub:
        raise AppError(404, "SUBSCRIPTION_NOT_FOUND", "This workspace has no billing record.")
    return sub


@router.get("")
def get_billing(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    """Every member can see the plan and usage (for banners and upgrade prompts); only the owner can change it."""
    with SessionLocal() as session:
        member = _require_member(session, workspace_id, current_user)
        sub = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
        ent = entitlements_for(sub)
        return {
            "workspace_id": str(workspace_id),
            "plan": ent.plan,
            "plan_name": PLANS[ent.plan].name,
            "state": ent.state,
            "status": sub.status if sub else None,
            "interval": sub.interval if sub else None,
            "can_write": ent.can_write,
            "can_manage": member.role == "owner",
            "billing_enabled": settings.billing_enabled,
            "has_billing_account": bool(sub and sub.stripe_customer_id),
            "trial_ends_at": sub.trial_ends_at if sub else None,
            "current_period_end": sub.current_period_end if sub else None,
            "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
            "grace_ends_at": sub.grace_ends_at if sub else None,
            "limits": ent.limits(),
            "usage": usage(session, workspace_id),
        }


@router.post("/checkout")
def create_checkout(workspace_id: UUID, payload: CheckoutRequest, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if sub.stripe_subscription_id and sub.status not in ("canceled", "incomplete_expired"):
            # Plan changes on a live subscription go through the Portal, which prorates; a second Checkout would double-bill.
            raise AppError(409, "ALREADY_SUBSCRIBED", "This workspace already has a subscription. Manage it in the billing portal.")
        price = price_for(payload.plan, payload.interval)
        if not settings.billing_enabled or not price:
            raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
        if not sub.stripe_customer_id:
            sub.stripe_customer_id = stripe_client.create_customer(current_user.email, str(workspace_id))
            session.commit()
        url = stripe_client.create_checkout_session(
            sub.stripe_customer_id, price, str(workspace_id),
            success_url=_url(payload.return_path, checkout="success"),
            cancel_url=_url(payload.return_path, checkout="cancel"),
        )
        return {"url": url}


@router.post("/portal")
def create_portal(workspace_id: UUID, payload: PortalRequest, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if not sub.stripe_customer_id:
            raise AppError(409, "NO_BILLING_ACCOUNT", "Choose a plan first; there is nothing to manage yet.")
        return {"url": stripe_client.create_portal_session(sub.stripe_customer_id, _url(payload.return_path))}
