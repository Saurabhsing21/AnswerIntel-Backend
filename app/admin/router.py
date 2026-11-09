"""Operator-only cost reporting. The one place money is shown; every other response stays free of dollar figures."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.auth.dependencies import require_admin
from app.billing.models import Subscription
from app.billing.plans import PLANS
from app.common.database import SessionLocal
from app.costs.models import AICall
from app.costs.service import workspace_cap
from app.scans.models import Scan
from app.projects.models import Project
from app.workspaces.models import Workspace

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _money(value) -> float:
    return float(Decimal(value or 0))


def _sum_since(session, since: datetime) -> Decimal:
    return Decimal(session.scalar(select(func.coalesce(func.sum(AICall.cost_usd), 0)).where(AICall.created_at >= since)))


def _grouped(session, since: datetime, *columns) -> list[dict]:
    """Spend and call count per distinct value of `columns`, biggest first."""
    rows = session.execute(
        select(*columns, func.coalesce(func.sum(AICall.cost_usd), 0), func.count(AICall.id), func.coalesce(func.sum(AICall.web_searches), 0))
        .where(AICall.created_at >= since)
        .group_by(*columns)
        .order_by(func.sum(AICall.cost_usd).desc())
    ).all()
    return [{"key": list(r[: len(columns)]), "cost": _money(r[-3]), "calls": r[-2], "web_searches": int(r[-1])} for r in rows]


def _revenue_per_month(sub: Subscription) -> Decimal:
    plan = PLANS.get(sub.plan)
    if plan is None:
        return Decimal(0)
    return Decimal(plan.price_yearly) / 12 if sub.interval == "year" else Decimal(plan.price_monthly)


@router.get("/costs")
def costs(days: int = Query(30, ge=1, le=365)):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    since = today - timedelta(days=days - 1)
    with SessionLocal() as session:
        day = func.date(func.timezone("UTC", AICall.created_at))
        spent = {
            d: Decimal(c)
            for d, c in session.execute(select(day, func.sum(AICall.cost_usd)).where(AICall.created_at >= since).group_by(day))
        }
        by_day = [
            {"date": (d := (since + timedelta(days=i)).date()).isoformat(), "cost": _money(spent.get(d, 0))} for i in range(days)
        ]

        month_by_workspace = session.execute(
            select(AICall.workspace_id, func.sum(AICall.cost_usd))
            .where(AICall.created_at >= month, AICall.workspace_id.is_not(None))
            .group_by(AICall.workspace_id)
            .order_by(func.sum(AICall.cost_usd).desc())
        ).all()
        workspaces = []
        for workspace_id, cost in month_by_workspace[:10]:
            sub = session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))
            cap = workspace_cap(session, workspace_id)
            workspaces.append({
                "workspace_id": str(workspace_id),
                "name": session.scalar(select(Workspace.name).where(Workspace.id == workspace_id)),
                "plan": sub.plan if sub else "none",
                "spend_this_month": _money(cost),
                "cap": _money(cap),
                "percent_of_cap": round(float(Decimal(cost) / cap * 100), 1) if cap else None,
            })

        scans = [
            {"id": s.id, "created_at": s.created_at.isoformat(), "brand": brand, "kind": s.kind, "status": s.status,
             "cost": _money(s.cost_usd), "ai_calls": s.ai_calls, "web_searches": s.web_searches}
            for s, brand in session.execute(
                select(Scan, Project.brand_name).join(Project, Project.id == Scan.project_id).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(20)
            )
        ]

        spend_by_workspace = {w: Decimal(c) for w, c in month_by_workspace}
        plans: dict[str, dict] = {}
        for sub in session.scalars(select(Subscription)):
            row = plans.setdefault(sub.plan, {"plan": sub.plan, "active_workspaces": 0, "revenue": Decimal(0), "ai_spend": Decimal(0)})
            row["ai_spend"] += spend_by_workspace.pop(sub.workspace_id, Decimal(0))
            if sub.status == "active":
                row["active_workspaces"] += 1
                row["revenue"] += _revenue_per_month(sub)
        if spend_by_workspace:  # workspaces that never had a subscription row
            plans["none"] = {"plan": "none", "active_workspaces": 0, "revenue": Decimal(0), "ai_spend": sum(spend_by_workspace.values(), Decimal(0))}
        margin = [
            {**r, "revenue": _money(r["revenue"]), "ai_spend": _money(r["ai_spend"]), "margin": _money(r["revenue"] - r["ai_spend"])}
            for r in plans.values()
        ]

        return {
            "days": days,
            "today": _money(_sum_since(session, today)),
            "this_month": _money(_sum_since(session, month)),
            "range_total": _money(sum(spent.values(), Decimal(0))),
            "by_day": by_day,
            "by_purpose": _grouped(session, since, AICall.purpose),
            "by_model": _grouped(session, since, AICall.model, AICall.engine),
            "top_workspaces": workspaces,
            "recent_scans": scans,
            "margin_by_plan": margin,
        }


@router.get("/runs/{scan_id}")
def run(scan_id: int):
    """One run's real cost: the scan's totals, a breakdown by purpose and engine, and every billed call.

    The cost is what the provider billed (ai_calls.cost_usd), never an estimate. `credits_charged` is what the
    plan's meter deducted, so `cost_per_credit` shows whether the pricing is holding against real spend."""
    with SessionLocal() as session:
        row = session.execute(
            select(Scan, Project.brand_name, Project.workspace_id)
            .join(Project, Project.id == Scan.project_id)
            .where(Scan.id == scan_id)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="No such scan")
        scan, brand, workspace_id = row

        breakdown = [
            {"purpose": purpose, "engine": engine, "calls": calls, "failed": failed,
             "cost": _money(cost), "input_tokens": int(in_tok), "output_tokens": int(out_tok), "web_searches": int(web)}
            for purpose, engine, calls, failed, cost, in_tok, out_tok, web in session.execute(
                select(
                    AICall.purpose, AICall.engine, func.count(AICall.id),
                    func.count(AICall.id).filter(AICall.status == "failed"),
                    func.coalesce(func.sum(AICall.cost_usd), 0),
                    func.coalesce(func.sum(AICall.input_tokens), 0),
                    func.coalesce(func.sum(AICall.output_tokens), 0),
                    func.coalesce(func.sum(AICall.web_searches), 0),
                )
                .where(AICall.scan_id == scan_id)
                .group_by(AICall.purpose, AICall.engine)
                .order_by(func.sum(AICall.cost_usd).desc())
            )
        ]
        calls = [
            {"id": c.id, "created_at": c.created_at.isoformat(), "purpose": c.purpose, "engine": c.engine,
             "model": c.model, "cost": _money(c.cost_usd), "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
             "reasoning_tokens": c.reasoning_tokens, "web_searches": c.web_searches, "latency_ms": c.latency_ms, "status": c.status}
            for c in session.scalars(
                select(AICall).where(AICall.scan_id == scan_id).order_by(AICall.cost_usd.desc(), AICall.id).limit(500)
            )
        ]
        cost = _money(scan.cost_usd)
        credits = float(scan.credits or 0)
        duration = int((scan.completed_at - scan.started_at).total_seconds() * 1000) if scan.started_at and scan.completed_at else None
        return {
            "scan": {
                "id": scan.id, "brand": brand, "workspace_id": str(workspace_id), "kind": scan.kind, "status": scan.status,
                "created_at": scan.created_at.isoformat(),
                "started_at": scan.started_at.isoformat() if scan.started_at else None,
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                "duration_ms": duration,
                "total_runs": scan.total_runs, "completed_runs": scan.completed_runs, "failed_runs": scan.failed_runs,
                "ai_calls": scan.ai_calls, "web_searches": scan.web_searches,
                "cost": cost, "credits_charged": credits,
                "cost_per_credit": round(cost / credits, 5) if credits else None,
            },
            "breakdown": breakdown,
            "calls": calls,
        }
