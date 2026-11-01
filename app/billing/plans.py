"""Plans and what each one allows. The single source for every per-workspace limit.

A new account's own workspace starts on the free trial: one project and one scan, no card. Any other workspace
has no plan until it pays. "trial" rows exist only for workspaces that predate billing and run out on their own. Stripe holds the prices; this file holds the limits. The frontend copy for the pricing section is
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
from app.providers.models import CATALOG, DISPLAY_NAMES

TRIAL_DAYS = 14  # only for the one-time backfill of pre-billing workspaces
GRACE_DAYS = 7  # writes keep working this long after a failed payment


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    projects: int
    active_prompts: int  # one pool shared by every project in the workspace
    answers_per_month: int  # AI answers (prompt x engine) in any 30 days: the cap that bounds our model cost
    competitors: int  # per project
    allowed_engines: tuple[str, ...]  # the AI engines scans may use on this plan; the rest of the catalog shows locked
    scans_per_day: int  # per workspace; an abuse guard, the answer cap is what bounds cost
    seats: int | None  # None = unlimited (seats cost nothing to serve)
    retention_days: int
    schedules: bool
    experiments: bool
    price_monthly: int = 0  # USD, display only; Stripe charges the price ids in settings
    price_yearly: int = 0
    scans_total: int | None = None  # scans ever, per workspace; only the free trial has one
    pro: bool = True  # drafts, re-tests, reports, exports, invites, alerts, more prompts: everything past the free trial


FREE_ENGINES = ("chatgpt_search",)
STARTER_ENGINES = FREE_ENGINES + ("perplexity",)
GROWTH_ENGINES = STARTER_ENGINES + ("claude",)  # Claude answers from model memory, no web search
PRO_ENGINES = GROWTH_ENGINES + ("gemini",)

# Same mechanism as Peec AI: one prompt pool, automatic weekly tracking, a monthly answer cap. Engines widen with the
# plan: ChatGPT Search on the free trial, + Perplexity on Starter, + Claude on Growth, + Gemini on Pro. All run on small
# models (see app/providers/models.py), roughly $0.003 to $0.01 per answer including analysis, so answers_per_month
# (prompts x that plan's engines x 4.3 weekly runs) keeps full use well under a third of the price.
# Yearly = 20% off, so it is a whole number a month.
STARTER = Plan("starter", "Starter", projects=2, active_prompts=30, answers_per_month=520, competitors=20,
               allowed_engines=STARTER_ENGINES, scans_per_day=2, seats=None, retention_days=183, schedules=True, experiments=False,
               price_monthly=20, price_yearly=192)
GROWTH = Plan("growth", "Growth", projects=4, active_prompts=80, answers_per_month=1400, competitors=50,
              allowed_engines=GROWTH_ENGINES, scans_per_day=4, seats=None, retention_days=365, schedules=True, experiments=True,
              price_monthly=50, price_yearly=480)
PRO = Plan("pro", "Pro", projects=10, active_prompts=160, answers_per_month=2800, competitors=100,
           allowed_engines=PRO_ENGINES, scans_per_day=10, seats=None, retention_days=730, schedules=True, experiments=True,
           price_monthly=100, price_yearly=960)
TRIAL = Plan("trial", "Trial", projects=4, active_prompts=80, answers_per_month=1400, competitors=50, allowed_engines=GROWTH_ENGINES,
             scans_per_day=4, seats=None, retention_days=365, schedules=True, experiments=True)  # legacy, ends on its own
# The free trial: one full scan of one brand, so people see their own results before paying. Cost: at most
# 10 prompts on ChatGPT Search (10 answers), about $0.10, and only after the email address is confirmed.
FREE = Plan("free", "Free trial", projects=1, active_prompts=10, answers_per_month=40, competitors=3, allowed_engines=FREE_ENGINES,
            scans_per_day=1, seats=None, retention_days=365, schedules=False, experiments=False, scans_total=1,
            pro=False)
# A workspace that has not paid yet: nothing allowed. Retention stays at the ceiling so nothing is purged early.
NONE = Plan("none", "No plan", projects=0, active_prompts=0, answers_per_month=0, competitors=0, allowed_engines=(),
            scans_per_day=0, seats=0, retention_days=365, schedules=False, experiments=False)

PLANS = {p.key: p for p in (NONE, FREE, TRIAL, STARTER, GROWTH, PRO)}


def engine_upgrades() -> dict[str, str]:
    """For each engine, the cheapest paid plan that includes it. Engines on no plan are absent."""
    upgrades: dict[str, str] = {}
    for plan in (STARTER, GROWTH, PRO):
        for key in plan.allowed_engines:
            upgrades.setdefault(key, plan.key)
    return upgrades


@dataclass(frozen=True)
class Entitlements:
    plan: str
    state: str  # unsubscribed | free | trialing | active | past_due | lapsed
    can_write: bool
    projects: int
    active_prompts: int
    answers_per_month: int
    competitors: int
    allowed_engines: tuple[str, ...]
    scans_per_day: int
    seats: int | None
    retention_days: int
    schedules: bool
    experiments: bool
    scans_total: int | None
    pro: bool
    locked_engines: tuple[str, ...]  # the catalog minus allowed_engines
    engine_upgrades: dict[str, str]  # locked engine key -> the plan key that unlocks it (absent: on no plan)

    def limits(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("plan", "state", "can_write")}


def state_of(sub: Subscription | None, now: datetime) -> str:
    if sub is None or sub.plan == "none":
        return "unsubscribed"
    if sub.plan == "free":
        return "free"
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
    locked = tuple(e.key for e in CATALOG if e.key not in plan.allowed_engines)
    return Entitlements(
        plan=plan.key,
        state=state,
        can_write=state not in ("lapsed", "unsubscribed"),
        projects=plan.projects,
        active_prompts=plan.active_prompts,
        answers_per_month=plan.answers_per_month,
        competitors=min(plan.competitors, settings.max_competitors),
        allowed_engines=plan.allowed_engines,
        scans_per_day=plan.scans_per_day,
        seats=plan.seats,
        retention_days=min(plan.retention_days, settings.raw_response_retention_days),
        schedules=plan.schedules,
        experiments=plan.experiments,
        scans_total=plan.scans_total,
        pro=plan.pro,
        locked_engines=locked,
        engine_upgrades={k: v for k, v in engine_upgrades().items() if k in locked},
    )


def entitlements(session: Session, workspace_id: UUID, now: datetime | None = None) -> Entitlements:
    sub = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
    return entitlements_for(sub, now)


def engines_for(engines: list, ent: Entitlements) -> list:
    """The engines a scan may use: only those the plan allows. A project's saved locked engines are skipped."""
    return [e for e in engines if e.key in ent.allowed_engines]


def check_engine_choice(ent: Entitlements, keys: list[str]) -> None:
    """A project's engine choice must fit the plan: every engine in it is one the plan allows."""
    for key in keys:
        if key in ent.allowed_engines:
            continue
        name = DISPLAY_NAMES.get(key, key)
        plan = engine_upgrades().get(key)
        message = f"{name} is on the {PLANS[plan].name} plan." if plan else f"{name} is not included in any plan."
        raise AppError(402, "PLAN_LIMIT", message, limit="engines")


def require_pro(ent: Entitlements, label: str) -> None:
    """Paid-plan features. The free trial shows them, locked, so people know what they get by upgrading."""
    require_active(ent)
    if not ent.pro:
        raise AppError(402, "PLAN_LIMIT", f"{label} {'are' if label.endswith('s') else 'is'} on paid plans, from $20 a month.", limit="pro")


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
    """Raise when `used` already fills the plan's `limit` (None = unlimited). Existing limit codes keep their old status."""
    require_active(ent)
    cap = getattr(ent, limit)
    if cap is not None and used >= cap:
        raise AppError(status, code, message, limit=limit)
