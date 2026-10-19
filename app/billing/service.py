import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.models import Subscription
from app.billing.plans import GRACE_DAYS
from app.common.config import settings
from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.models import Prompt
from app.scans.models import Scan
from app.workspaces.models import WorkspaceMember

log = logging.getLogger(__name__)

# A subscription in one of these states never replaces the one a workspace already has.
_NOT_LIVE = ("incomplete", "incomplete_expired", "canceled", "unpaid")


def open_billing(session: Session, workspace_id: UUID) -> Subscription:
    """Billing record for a new workspace. There is no free plan: it can do nothing until Checkout is paid."""
    sub = Subscription(workspace_id=workspace_id, plan="none", status="none")
    session.add(sub)
    return sub


def scans_today(session: Session, workspace_id: UUID, now: datetime | None = None, days: int = 1) -> int:
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return session.scalar(
        select(func.count()).select_from(Scan).join(Project, Project.id == Scan.project_id)
        .where(Project.workspace_id == workspace_id, Scan.created_at >= since)
    ) or 0


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
        "per_project": [
            {"id": str(pid), "brand_name": name, "active_prompts": p, "competitors": c} for pid, name, p, c in rows
        ],
    }


def price_ids() -> dict[str, tuple[str, str]]:
    """Stripe price id -> (plan, interval)."""
    pairs = {
        settings.stripe_price_starter_monthly: ("starter", "month"),
        settings.stripe_price_starter_yearly: ("starter", "year"),
        settings.stripe_price_pro_monthly: ("pro", "month"),
        settings.stripe_price_pro_yearly: ("pro", "year"),
    }
    return {price: plan for price, plan in pairs.items() if price}


def price_for(plan: str, interval: str) -> str | None:
    return next((price for price, pair in price_ids().items() if pair == (plan, interval)), None)


def _timestamp(value) -> datetime | None:
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def find_subscription(session: Session, data: dict) -> Subscription | None:
    workspace_id = (data.get("metadata") or {}).get("workspace_id")
    if workspace_id:
        try:
            sub = session.scalar(select(Subscription).where(Subscription.workspace_id == UUID(workspace_id)))
        except ValueError:
            sub = None
        if sub:
            return sub
    sub = session.scalar(select(Subscription).where(Subscription.stripe_subscription_id == data["id"]))
    if sub or not data.get("customer"):
        return sub
    return session.scalar(select(Subscription).where(Subscription.stripe_customer_id == data["customer"]))


def apply_stripe_subscription(session: Session, data: dict, now: datetime | None = None) -> Subscription | None:
    """Mirror a Stripe subscription object onto the workspace's row. Status always comes from Stripe."""
    now = now or datetime.now(timezone.utc)
    sub = find_subscription(session, data)
    if not sub:
        log.warning("Stripe subscription %s matches no workspace", data.get("id"))
        return None
    status = data.get("status", "")
    if sub.stripe_subscription_id != data["id"] and status in _NOT_LIVE:
        # A late event for an old subscription, or a checkout that never paid: keep what the workspace has.
        log.info("Ignoring %s subscription %s for workspace %s", status, data["id"], sub.workspace_id)
        return sub
    item = ((data.get("items") or {}).get("data") or [{}])[0]
    pair = price_ids().get((item.get("price") or {}).get("id"))
    if not pair:
        log.error("Stripe subscription %s uses a price that is not configured", data["id"])
        return sub
    sub.plan, sub.interval = pair
    sub.status = status
    sub.stripe_subscription_id = data["id"]
    sub.stripe_customer_id = data.get("customer") or sub.stripe_customer_id
    # Newer Stripe API versions keep the period on the subscription item.
    sub.current_period_end = _timestamp(item.get("current_period_end") or data.get("current_period_end"))
    sub.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
    if status == "past_due":
        sub.grace_ends_at = sub.grace_ends_at or now + timedelta(days=GRACE_DAYS)
    elif status in ("active", "trialing"):
        sub.grace_ends_at = None
    return sub
