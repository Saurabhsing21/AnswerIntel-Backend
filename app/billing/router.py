import uuid
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing import cashfree_client
from app.billing.models import Subscription
from app.billing.plans import PLANS, entitlements_for
from app.billing.service import apply_and_replace, apply_cashfree_subscription, cancel_replaced, price_for, usage
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.users.models import User
from app.workspaces.router import _require_member

router = APIRouter(prefix="/workspaces/{workspace_id}/billing", tags=["Billing"])

# Same-site path only (no scheme, no //host), so Cashfree can never send people somewhere else.
RETURN_PATH = r"^/([^/\s\\][^\s\\]*)?$"


# Cashfree requires a phone on every subscription: digits with an optional leading +, country code included.
PHONE = r"^\+?[0-9]{8,15}$"
# A live subscription can be canceled or changed; after these it can only be replaced by a new checkout.
_ENDED = ("canceled", "incomplete_expired")


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]
    interval: Literal["month", "year"] = "month"
    return_path: str = Field(default="/projects", pattern=RETURN_PATH, max_length=500)
    phone: str | None = Field(default=None, pattern=PHONE)


class ChangeRequest(BaseModel):
    plan: Literal["starter", "growth", "pro"]
    interval: Literal["month", "year"] = "month"
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
            "has_billing_account": bool(sub and sub.cashfree_subscription_id),
            "has_billing_phone": bool(sub and sub.billing_phone),
            "trial_ends_at": sub.trial_ends_at if sub else None,
            "current_period_end": sub.current_period_end if sub else None,
            "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
            "grace_ends_at": sub.grace_ends_at if sub else None,
            "limits": ent.limits(),
            "usage": usage(session, workspace_id),
        }


def _live(session, workspace_id: UUID) -> Subscription:
    sub = _subscription(session, workspace_id)
    if not sub.cashfree_subscription_id or sub.status in _ENDED:
        raise AppError(409, "NO_ACTIVE_SUBSCRIPTION", "This workspace has no active subscription to change.")
    return sub


def _ensure_plan(plan: str, interval: str) -> tuple[str, int]:
    amount = price_for(plan, interval)
    return cashfree_client.ensure_plan(plan, interval, PLANS[plan].name, amount), amount


def _refresh(session, sub: Subscription) -> None:
    """Applies Cashfree's copy right away, so the owner sees the change without waiting for the webhook."""
    apply_cashfree_subscription(session, cashfree_client.retrieve_subscription(sub.cashfree_subscription_id))
    session.commit()


def _start_checkout(session, sub: Subscription, plan: str, interval: str, email: str, return_path: str) -> dict:
    """A new Cashfree subscription; the browser opens its hosted checkout with the returned session id."""
    plan_id, amount = _ensure_plan(plan, interval)
    subscription_id = f"ws_{sub.workspace_id.hex[:12]}_{uuid.uuid4().hex[:12]}"
    session_id = cashfree_client.create_subscription(
        subscription_id, plan_id, amount, interval, email, sub.billing_phone, str(sub.workspace_id),
        # Cashfree comes back with a cross-site POST, which drops the session cookie; the frontend's
        # /billing/return turns it into a normal redirect to return_path.
        return_url=_url("/billing/return", to=quote(return_path, safe="")),
    )
    sub.cashfree_pending_id = subscription_id
    session.commit()
    return {"session_id": session_id, "mode": "production" if settings.cashfree_env == "production" else "sandbox"}


@router.post("/checkout")
def create_checkout(workspace_id: UUID, payload: CheckoutRequest, current_user: User = Depends(get_current_user)):
    """Starts a Cashfree subscription; the browser opens its hosted checkout with the returned session id."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if sub.cashfree_subscription_id and sub.status not in _ENDED:
            # A second subscription would charge twice; plan changes go through /change.
            raise AppError(409, "ALREADY_SUBSCRIBED", "This workspace already has a subscription. Change or cancel it from billing.")
        if not settings.billing_enabled:
            raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
        if payload.phone:
            sub.billing_phone = payload.phone
            session.commit()
        if not sub.billing_phone:
            raise AppError(422, "PHONE_REQUIRED", "Add a phone number to continue to payment.")
        return _start_checkout(session, sub, payload.plan, payload.interval, current_user.email, payload.return_path)


@router.post("/sync")
def sync(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    """Back from checkout: applies the pending subscription as Cashfree has it now, so the plan does not wait for
    the webhook. Safe to call any time; an unpaid checkout changes nothing."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _subscription(session, workspace_id)
        if not sub.cashfree_pending_id or not settings.billing_enabled:
            return {"synced": False}
        _, replaced = apply_and_replace(session, cashfree_client.retrieve_subscription(sub.cashfree_pending_id))
        session.commit()
        cancel_replaced(replaced)
        return {"synced": sub.cashfree_subscription_id == sub.cashfree_pending_id}


@router.post("/change")
def change_plan(workspace_id: UUID, payload: ChangeRequest, current_user: User = Depends(get_current_user)):
    """Moves a live subscription to another plan or period. Cashfree never raises a mandate above what the customer
    approved, so a dearer plan is a new checkout (returns a session id; the old subscription is canceled once the new
    one is paid). A cheaper one is changed in place: new limits now, the new price from the next renewal."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _live(session, workspace_id)
        if (sub.plan, sub.interval) == (payload.plan, payload.interval):
            raise AppError(409, "SAME_PLAN", "This workspace is already on that plan.")
        if price_for(payload.plan, payload.interval) > price_for(sub.plan, sub.interval):
            return _start_checkout(session, sub, payload.plan, payload.interval, current_user.email, payload.return_path)
        plan_id, _ = _ensure_plan(payload.plan, payload.interval)
        cashfree_client.manage_subscription(sub.cashfree_subscription_id, "CHANGE_PLAN", plan_id)
        _refresh(session, sub)
        return {"plan": sub.plan, "interval": sub.interval}


@router.post("/cancel")
def cancel(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    """Stops future charges. Everything keeps working until the end of the period already paid for."""
    with SessionLocal() as session:
        _require_owner(session, workspace_id, current_user)
        sub = _live(session, workspace_id)
        cashfree_client.cancel_subscription(sub.cashfree_subscription_id)
        _refresh(session, sub)
        return {"status": sub.status, "current_period_end": sub.current_period_end}
