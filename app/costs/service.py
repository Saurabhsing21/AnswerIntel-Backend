import logging
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

from app.common.database import SessionLocal
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
