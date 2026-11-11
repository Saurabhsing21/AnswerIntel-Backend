import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import paddle_client
from app.billing.models import PaddleCustomer, Subscription
from app.billing.plans import GRACE_DAYS, PLANS
from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.models import Prompt
from app.scans.models import Scan
from app.workspaces.models import WorkspaceMember

log = logging.getLogger(__name__)

# A subscription in a _NOT_LIVE state never replaces the one a workspace already has.
_NOT_LIVE = ("canceled", "paused")
_LIVE = ("active", "trialing")


def open_billing(session: Session, workspace_id: UUID, trial: bool = False) -> Subscription:
    """Billing record for a new workspace: the free trial for a new account's own workspace, otherwise no plan
    (it can do nothing until Checkout is paid)."""
    sub = Subscription(workspace_id=workspace_id, plan="free" if trial else "none", status="active" if trial else "none")
    session.add(sub)
    return sub


def scans_ever(session: Session, workspace_id: UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(Scan).join(Project, Project.id == Scan.project_id).where(Project.workspace_id == workspace_id)
    ) or 0


def scans_today(session: Session, workspace_id: UUID, now: datetime | None = None, days: int = 1) -> int:
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return session.scalar(
        select(func.count()).select_from(Scan).join(Project, Project.id == Scan.project_id)
        .where(Project.workspace_id == workspace_id, Scan.created_at >= since)
    ) or 0


def credits_used(session: Session, workspace_id: UUID, now: datetime | None = None) -> float:
    """Credits the workspace's scans were charged in the last 30 days."""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    return float(session.scalar(
        select(func.coalesce(func.sum(Scan.credits), 0)).join(Project, Project.id == Scan.project_id)
        .where(Project.workspace_id == workspace_id, Scan.created_at >= since)
    ) or 0)


def active_prompts(session: Session, workspace_id: UUID) -> int:
    """Active prompts across every project: the plan's prompt pool."""
    return session.scalar(
        select(func.count()).select_from(Prompt).join(Project, Project.id == Prompt.project_id)
        .where(Project.workspace_id == workspace_id, Prompt.is_active)
    ) or 0


def pool_holders(session: Session, workspace_id: UUID) -> list[dict]:
    """Projects holding the question pool, biggest first: who to turn questions off in."""
    rows = session.execute(
        select(Project.id, Project.brand_name, func.count(Prompt.id))
        .join(Prompt, Prompt.project_id == Project.id)
        .where(Project.workspace_id == workspace_id, Prompt.is_active)
        .group_by(Project.id, Project.brand_name)
        .order_by(func.count(Prompt.id).desc(), Project.brand_name)
    ).all()
    return [{"project_id": str(pid), "brand": brand, "active": n} for pid, brand, n in rows]


def project_count(session: Session, workspace_id: UUID) -> int:
    return session.scalar(select(func.count()).select_from(Project).where(Project.workspace_id == workspace_id)) or 0


def seat_count(session: Session, workspace_id: UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    ) or 0


def usage(session: Session, workspace_id: UUID) -> dict:
    prompts = (
        select(func.count()).select_from(Prompt).where(Prompt.project_id == Project.id, Prompt.is_active).scalar_subquery()
    )
    competitors = select(func.count()).select_from(Competitor).where(Competitor.project_id == Project.id).scalar_subquery()
    rows = session.execute(
        select(Project.id, Project.brand_name, prompts, competitors)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.created_at)
    ).all()
    return {
        "projects": len(rows),
        "seats": seat_count(session, workspace_id),
        "scans_today": scans_today(session, workspace_id),
        "scans_30_days": scans_today(session, workspace_id, days=30),
        "scans_total": scans_ever(session, workspace_id),
        "credits_30_days": credits_used(session, workspace_id),
        "active_prompts": active_prompts(session, workspace_id),
        "per_project": [
            {"id": str(pid), "brand_name": name, "active_prompts": p, "competitors": c} for pid, name, p, c in rows
        ],
    }


def _timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def apply_paddle_customer(session: Session, data: dict) -> PaddleCustomer:
    """Upsert keyed on Paddle's customer id, so a redelivered or reordered event just writes the same row again."""
    customer = session.get(PaddleCustomer, data["id"]) or PaddleCustomer(customer_id=data["id"])
    customer.email = data.get("email") or customer.email
    session.add(customer)
    return customer


def find_subscription(session: Session, data: dict) -> Subscription | None:
    """The workspace a Paddle subscription belongs to: named in custom_data at checkout, or already linked."""
    workspace_id = (data.get("custom_data") or {}).get("workspace_id")
    if workspace_id:
        try:
            sub = session.scalar(select(Subscription).where(Subscription.workspace_id == UUID(workspace_id)))
        except ValueError:
            sub = None
        if sub:
            return sub
    return session.scalar(select(Subscription).where(Subscription.paddle_subscription_id == data["id"]))


def apply_paddle_subscription(session: Session, data: dict, now: datetime | None = None) -> tuple[Subscription | None, str | None]:
    """Mirror a Paddle subscription (webhook payload or API response) onto its workspace's row. Status always comes
    from Paddle. Returns the row and the id of a different live subscription it replaced, which the caller cancels
    once this is committed so nobody pays twice."""
    now = now or datetime.now(timezone.utc)
    sub = find_subscription(session, data)
    if not sub:
        log.warning("Paddle subscription %s matches no workspace", data.get("id"))
        return None, None
    status = data.get("status", "")
    same = sub.paddle_subscription_id == data["id"]
    if not same and status in _NOT_LIVE:
        # A late event for an old subscription: keep what the workspace has.
        log.info("Ignoring %s subscription %s for workspace %s", status, data["id"], sub.workspace_id)
        return sub, None
    changed_at = _timestamp(data.get("updated_at"))
    if same and changed_at and sub.paddle_updated_at and changed_at < sub.paddle_updated_at:
        log.info("Ignoring out-of-date copy of subscription %s", data["id"])
        return sub, None
    price = ((data.get("items") or [{}])[0].get("price") or {})
    plan, interval = (price.get("custom_data") or {}).get("plan"), (price.get("custom_data") or {}).get("interval")
    if plan not in PLANS or interval not in ("month", "year"):
        log.error("Paddle subscription %s uses price %s, which has no plan in its custom_data", data["id"], price.get("id"))
        return sub, None
    replaced = sub.paddle_subscription_id if (
        sub.paddle_subscription_id and not same and sub.status in _LIVE and status in _LIVE
    ) else None
    sub.plan, sub.interval, sub.status = plan, interval, status
    sub.paddle_subscription_id = data["id"]
    sub.paddle_customer_id = data.get("customer_id") or sub.paddle_customer_id
    sub.paddle_price_id, sub.paddle_product_id = price.get("id"), price.get("product_id")
    sub.paddle_updated_at = changed_at
    period = data.get("current_billing_period") or {}
    sub.current_period_end = _timestamp(period.get("ends_at")) or _timestamp(data.get("next_billed_at")) or sub.current_period_end
    change = data.get("scheduled_change") or {}
    sub.scheduled_change_action = change.get("action")
    sub.scheduled_change_at = _timestamp(change.get("effective_at"))
    sub.cancel_at_period_end = change.get("action") == "cancel"
    if status == "past_due":
        sub.grace_ends_at = sub.grace_ends_at or now + timedelta(days=GRACE_DAYS)
    elif status in _LIVE:
        sub.grace_ends_at = None
    return sub, replaced


def cancel_replaced(subscription_id: str | None) -> None:
    if not subscription_id:
        return
    try:
        paddle_client.cancel_subscription(subscription_id)
    except Exception:  # the new plan is live either way; this needs a person to cancel it by hand
        log.error("Could not cancel replaced Paddle subscription %s", subscription_id, exc_info=True)
