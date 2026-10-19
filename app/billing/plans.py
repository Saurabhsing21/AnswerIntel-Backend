"""Plans and what each one allows. The single source for every per-workspace limit.

There is no free plan: a new workspace has no plan until it pays. Trial rows exist only for workspaces
that predate billing (backfilled once) and run out on their own. Stripe holds the prices; this file holds the limits. The frontend copy for the pricing section is
frontend/lib/billing/plans.ts; keep the two in step when a number changes. The global settings
(max_active_prompts, max_competitors, max_scans_per_day, raw_response_retention_days) stay as hard
ceilings: a plan can only lower them.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import Subscription
from app.common.config import settings
from app.common.errors import AppError

TRIAL_DAYS = 14  # only for the one-time backfill of pre-billing workspaces
GRACE_DAYS = 7  # writes keep working this long after a failed payment


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    projects: int
    active_prompts: int  # per project
    competitors: int  # per project
    engines: int | None  # None = every configured engine
    scans_per_day: int  # per workspace, all projects together
    seats: int
    retention_days: int
    schedules: bool
    experiments: bool
    price_monthly: int = 0  # USD, display only; Stripe charges the price ids in settings
    price_yearly: int = 0


STARTER = Plan("starter", "Starter", projects=1, active_prompts=25, competitors=3, engines=2, scans_per_day=3,
               seats=2, retention_days=183, schedules=False, experiments=False, price_monthly=20, price_yearly=200)
GROWTH = Plan("growth", "Growth", projects=3, active_prompts=75, competitors=8, engines=None, scans_per_day=10,
              seats=5, retention_days=365, schedules=True, experiments=True, price_monthly=50, price_yearly=500)
PRO = Plan("pro", "Pro", projects=10, active_prompts=200, competitors=15, engines=None, scans_per_day=30,
           seats=15, retention_days=730, schedules=True, experiments=True, price_monthly=100, price_yearly=1000)
TRIAL = Plan("trial", "Trial", projects=5, active_prompts=100, competitors=10, engines=None, scans_per_day=20,
             seats=10, retention_days=365, schedules=True, experiments=True)  # legacy: Pro limits, ends on its own
# A workspace that has not paid yet: nothing allowed. Retention stays at the ceiling so nothing is purged early.
NONE = Plan("none", "No plan", projects=0, active_prompts=0, competitors=0, engines=0, scans_per_day=0,
            seats=0, retention_days=365, schedules=False, experiments=False)

PLANS = {p.key: p for p in (NONE, TRIAL, STARTER, GROWTH, PRO)}


@dataclass(frozen=True)
class Entitlements:
    plan: str
    state: str  # unsubscribed | trialing | active | past_due | lapsed
    can_write: bool
    projects: int
    active_prompts: int
    competitors: int
    engines: int | None
    scans_per_day: int
    seats: int
    retention_days: int
    schedules: bool
    experiments: bool

    def limits(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("plan", "state", "can_write")}


def state_of(sub: Subscription | None, now: datetime) -> str:
    if sub is None or sub.plan == "none":
        return "unsubscribed"
    if sub.plan == "trial":
        return "trialing" if sub.trial_ends_at and sub.trial_ends_at > now else "lapsed"
    if sub.status in ("active", "trialing"):
        return "active"
    if sub.status == "past_due" and (sub.grace_ends_at is None or sub.grace_ends_at > now):
        return "past_due"
    return "lapsed"  # canceled, unpaid, incomplete_expired, or past_due beyond the grace period


def entitlements_for(sub: Subscription | None, now: datetime | None = None) -> Entitlements:
    now = now or datetime.now(timezone.utc)
    plan = PLANS.get(sub.plan if sub else "none", NONE)
    state = state_of(sub, now)
    return Entitlements(
        plan=plan.key,
        state=state,
        can_write=state not in ("lapsed", "unsubscribed"),
        projects=plan.projects,
        active_prompts=min(plan.active_prompts, settings.max_active_prompts),
        competitors=min(plan.competitors, settings.max_competitors),
        engines=plan.engines,
        scans_per_day=plan.scans_per_day,
        seats=plan.seats,
        retention_days=min(plan.retention_days, settings.raw_response_retention_days),
        schedules=plan.schedules,
        experiments=plan.experiments,
    )


def entitlements(session: Session, workspace_id: UUID, now: datetime | None = None) -> Entitlements:
    sub = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
    return entitlements_for(sub, now)


def engines_for(engines: list, ent: Entitlements) -> list:
    """The engines a scan may use: the first N configured ones on plans with an engine limit."""
    return engines if ent.engines is None else engines[: ent.engines]


def require_active(ent: Entitlements) -> None:
    """Lapsed workspaces are read-only: they can view and export, nothing that adds data or spends money."""
    if not ent.can_write:
        message = (
            "Choose a plan to start scanning." if ent.state == "unsubscribed"
            else "This workspace's plan is not active. Renew it to keep scanning and adding data."
        )
        raise AppError(402, "SUBSCRIPTION_INACTIVE", message, limit="subscription")


def require_feature(ent: Entitlements, feature: str, label: str) -> None:
    require_active(ent)
    if not getattr(ent, feature):
        raise AppError(402, "PLAN_LIMIT", f"{label} are not included in the {PLANS[ent.plan].name} plan.", limit=feature)


def require_room(ent: Entitlements, limit: str, used: int, message: str, code: str = "PLAN_LIMIT", status: int = 402) -> None:
    """Raise when `used` already fills the plan's `limit`. Existing limit codes keep their old status."""
    require_active(ent)
    if used >= getattr(ent, limit):
        raise AppError(status, code, message, limit=limit)
