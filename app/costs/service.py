import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.billing.plans import PLANS, entitlements
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.costs.models import AICall

log = logging.getLogger(__name__)

SCOPE_FIELDS = ("workspace_id", "project_id", "user_id", "scan_id", "purpose", "engine")

_scope: ContextVar[dict] = ContextVar("cost_scope", default={})


@contextmanager
def cost_scope(**fields):
    """Attribute every provider call made inside the block. Inner fields override outer ones; None leaves them alone."""
    unknown = set(fields) - set(SCOPE_FIELDS)
    if unknown:
        raise TypeError(f"Unknown cost scope fields: {sorted(unknown)}")
    token = _scope.set({**_scope.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _scope.reset(token)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def record_call(
    *,
    provider: str,
    model: str,
    usage: dict | None,
    generation_id: str | None,
    cost_usd,
    web_searches: int,
    status: str,
    latency_ms: int | None,
    ai_response_id: int | None = None,
) -> None:
    """Write one ai_calls row using the current cost scope. Bookkeeping must never break the call it describes."""
    try:
        usage = usage or {}
        scope = _scope.get()
        input_details = usage.get("prompt_tokens_details") or {}
        output_details = usage.get("completion_tokens_details") or {}
        has_cost = cost_usd is not None
        with SessionLocal() as session:
            session.add(
                AICall(
                    workspace_id=scope.get("workspace_id"),
                    project_id=scope.get("project_id"),
                    user_id=scope.get("user_id"),
                    scan_id=scope.get("scan_id"),
                    ai_response_id=ai_response_id,
                    purpose=scope.get("purpose") or "other",
                    provider=provider,
                    model=model,
                    engine=scope.get("engine"),
                    generation_id=generation_id,
                    input_tokens=_int(usage.get("prompt_tokens")),
                    output_tokens=_int(usage.get("completion_tokens")),
                    reasoning_tokens=_int(output_details.get("reasoning_tokens")),
                    cached_tokens=_int(input_details.get("cached_tokens")),
                    web_searches=web_searches,
                    cost_usd=Decimal(str(cost_usd)) if has_cost else Decimal(0),
                    cost_source="provider" if has_cost else "estimated",
                    status=status,
                    latency_ms=latency_ms,
                )
            )
            session.commit()
    except Exception:
        log.exception("Could not record %s call cost", provider)


def finalize_scan_cost(session, scan) -> None:
    """Set the scan's cost totals from its ledger rows. Recomputed, never incremented, so it is safe to repeat."""
    cost, calls, searches = session.execute(
        select(func.coalesce(func.sum(AICall.cost_usd), 0), func.count(AICall.id), func.coalesce(func.sum(AICall.web_searches), 0)).where(
            AICall.scan_id == scan.id
        )
    ).one()
    scan.cost_usd = Decimal(cost)
    scan.ai_calls = int(calls)
    scan.web_searches = int(searches)


_alerted_on: date | None = None


def _sum_since(session, since: datetime, workspace_id: UUID | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(AICall.cost_usd), 0)).where(AICall.created_at >= since)
    if workspace_id is not None:
        query = query.where(AICall.workspace_id == workspace_id)
    return Decimal(session.scalar(query))


def spend_today(session) -> Decimal:
    now = datetime.now(timezone.utc)
    return _sum_since(session, now.replace(hour=0, minute=0, second=0, microsecond=0))


def workspace_spend_this_month(session, workspace_id: UUID) -> Decimal:
    now = datetime.now(timezone.utc)
    return _sum_since(session, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), workspace_id)


def workspace_cap(session, workspace_id: UUID) -> Decimal:
    price = PLANS[entitlements(session, workspace_id).plan].price_monthly
    if price == 0:
        return Decimal(str(settings.free_workspace_cost_cap_usd))
    return Decimal(price) * Decimal(str(settings.workspace_cost_cap_ratio))


def check_budget(session, workspace_id: UUID) -> None:
    """Refuse to start a scan once the global daily budget or this workspace's monthly cap is spent."""
    global _alerted_on
    if settings.daily_ai_budget_usd > 0:
        spent = spend_today(session)
        if spent >= Decimal(str(settings.daily_ai_budget_usd)):
            today = datetime.now(timezone.utc).date()
            if _alerted_on != today:
                _alerted_on = today
                log.error("Daily AI budget reached: spent $%s of $%s today. Scans are paused until tomorrow (UTC).", spent, settings.daily_ai_budget_usd)
            raise AppError(429, "AI_BUDGET_REACHED", "Scans are paused for today while we add capacity. Try again tomorrow.")
    if workspace_spend_this_month(session, workspace_id) >= workspace_cap(session, workspace_id):
        raise AppError(402, "WORKSPACE_COST_CAP", "This workspace has reached this month's scan capacity. It resets on the 1st, or upgrade for more.")
