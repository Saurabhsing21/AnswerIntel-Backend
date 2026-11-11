from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing import paddle_client
from app.billing.models import Subscription
from app.billing.plans import PLANS, entitlements_for
from app.billing.service import apply_paddle_subscription, usage
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.users.models import User
from app.workspaces.router import _require_member

router = APIRouter(prefix="/workspaces/{workspace_id}/billing", tags=["Billing"])

# Checkout itself runs in the browser (Paddle.js) with the workspace id in custom_data; the webhook applies it.


class ChangeRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]
    interval: Literal["month", "year"] = "month"


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
            "has_billing_account": bool(sub and sub.paddle_customer_id),
            "trial_ends_at": sub.trial_ends_at if sub else None,
            "current_period_end": sub.current_period_end if sub else None,
            "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
            "grace_ends_at": sub.grace_ends_at if sub else None,
            "limits": ent.limits(),
            "usage": usage(session, workspace_id),
        }


@router.post("/portal")
def create_portal(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    """A Paddle customer portal link (invoices, payment method, cancel). The customer id comes from this workspace's
    own billing row, never from the browser, and only its owner may open it."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if not sub.paddle_customer_id:
            raise AppError(409, "NO_BILLING_ACCOUNT", "Choose a plan first; there is nothing to manage yet.")
        subscriptions = [sub.paddle_subscription_id] if sub.paddle_subscription_id else []
        return {"url": paddle_client.portal_url(sub.paddle_customer_id, subscriptions)}


@router.post("/change")
def change_plan(workspace_id: UUID, payload: ChangeRequest, current_user: User = Depends(get_current_user)):
    """Moves a live subscription to another plan or period now. Paddle charges (or credits) the prorated difference."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if not sub.paddle_subscription_id or sub.status not in ("active", "trialing", "past_due"):
            raise AppError(409, "NO_ACTIVE_SUBSCRIPTION", "This workspace has no active subscription to change.")
        if (sub.plan, sub.interval) == (payload.plan, payload.interval):
            raise AppError(409, "SAME_PLAN", "This workspace is already on that plan.")
        data = paddle_client.change_price(sub.paddle_subscription_id, paddle_client.price_id_for(payload.plan, payload.interval))
        # Apply Paddle's copy now, so the owner sees the new plan without waiting for the webhook.
        apply_paddle_subscription(session, data)
        session.commit()
        return {"plan": sub.plan, "interval": sub.interval}
