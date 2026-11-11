import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import cashfree_client
from app.billing.cashfree_client import plan_of
from app.billing.models import Subscription
from app.billing.plans import GRACE_DAYS, PLANS
from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.models import Prompt
from app.scans.models import Scan
from app.workspaces.models import WorkspaceMember

log = logging.getLogger(__name__)

# A subscription in one of these states never replaces the one a workspace already has.
_NOT_LIVE = ("incomplete", "incomplete_expired", "canceled", "paused")


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


def price_for(plan: str, interval: str) -> int:
    """What a plan costs per period, in settings.cashfree_currency."""
    return PLANS[plan].price_yearly if interval == "year" else PLANS[plan].price_monthly


# Cashfree subscription status -> ours. ON_HOLD is a renewal charge that failed (cards and eNACH).
_STATUS = {
    "ACTIVE": "active",
    "ON_HOLD": "past_due",
    "PAUSED": "paused",
    "CUSTOMER_PAUSED": "paused",
    "CANCELLED": "canceled",
    "CUSTOMER_CANCELLED": "canceled",
    "EXPIRED": "canceled",
    "COMPLETED": "canceled",
    "CARD_EXPIRED": "canceled",
    "INITIALIZED": "incomplete",
    "BANK_APPROVAL_PENDING": "incomplete",
    "LINK_EXPIRED": "incomplete_expired",
}
_IST = timezone(timedelta(hours=5, minutes=30))


def _timestamp(value: str | None) -> datetime | None:
    """Cashfree sends ISO times, sometimes without an offset; those are IST."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_IST)


def find_subscription(session: Session, data: dict) -> Subscription | None:
    workspace_id = (data.get("subscription_tags") or {}).get("workspace_id")
    if workspace_id:
        try:
            sub = session.scalar(select(Subscription).where(Subscription.workspace_id == UUID(workspace_id)))
        except ValueError:
            sub = None
        if sub:
            return sub
    return session.scalar(select(Subscription).where(Subscription.cashfree_subscription_id == data["subscription_id"]))


def apply_cashfree_subscription(session: Session, data: dict, charge_failed: bool = False,
                                now: datetime | None = None) -> Subscription | None:
    """Mirror a Cashfree subscription onto the workspace's row. Status always comes from Cashfree, except that a
    failed renewal charge counts as past_due while Cashfree still retries it (UPI AutoPay stays ACTIVE meanwhile)."""
    now = now or datetime.now(timezone.utc)
    sub = find_subscription(session, data)
    if not sub:
        log.warning("Cashfree subscription %s matches no workspace", data.get("subscription_id"))
        return None
    status = _STATUS.get(data.get("subscription_status", ""), (data.get("subscription_status") or "").lower())
    if sub.cashfree_subscription_id != data["subscription_id"] and status in _NOT_LIVE:
        # A late event for an old subscription, or a checkout that never paid: keep what the workspace has.
        log.info("Ignoring %s subscription %s for workspace %s", status, data["subscription_id"], sub.workspace_id)
        return sub
    pair = plan_of((data.get("plan_details") or {}).get("plan_id"))
    if not pair:
        log.error("Cashfree subscription %s is on a plan that is not ours", data["subscription_id"])
        return sub
    if charge_failed and status == "active":
        status = "past_due"
    sub.plan, sub.interval = pair
    sub.status = status
    sub.cashfree_subscription_id = data["subscription_id"]
    # The next charge date is the end of the paid period; a canceled subscription has none, so keep the last one.
    sub.current_period_end = (
        _timestamp(data.get("next_schedule_date")) or _timestamp(data.get("subscription_first_charge_time"))
        or sub.current_period_end
    )
    # Cashfree cancels at once; the period already paid for still runs to its end (plans.state_of).
    sub.cancel_at_period_end = status == "canceled"
    if status == "past_due":
        sub.grace_ends_at = sub.grace_ends_at or now + timedelta(days=GRACE_DAYS)
    elif status == "active":
        sub.grace_ends_at = None
    return sub


def apply_and_replace(session: Session, data: dict, charge_failed: bool = False) -> tuple[Subscription | None, str | None]:
    """apply_cashfree_subscription, plus the id of the subscription it replaced (an upgrade paid through a new
    checkout), which the caller cancels in Cashfree once this is committed so nobody pays for both."""
    existing = find_subscription(session, data)
    old = existing.cashfree_subscription_id if existing else None
    sub = apply_cashfree_subscription(session, data, charge_failed=charge_failed)
    replaced = old if sub and old and old != sub.cashfree_subscription_id and sub.status == "active" else None
    return sub, replaced


def cancel_replaced(subscription_id: str | None) -> None:
    if not subscription_id:
        return
    try:
        cashfree_client.cancel_subscription(subscription_id)
    except Exception:  # the new plan is live either way; this needs a person to cancel it by hand
        log.error("Could not cancel replaced Cashfree subscription %s", subscription_id, exc_info=True)

