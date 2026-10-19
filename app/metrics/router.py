from collections import Counter, defaultdict
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.metrics.stats import margin, significant
from app.analysis.models import Citation, CompetitorObservation, Mention
from app.auth.dependencies import get_current_user
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.competitors.models import Competitor
from app.metrics.models import CompetitorMetric, MetricSnapshot
from app.metrics.service import load_observations
from app.opportunities.models import Opportunity
from app.opportunities.router import serialize as serialize_opportunity
from app.opportunities.service import IMPACT_ORDER
from app.prompts.models import Prompt, ScanPrompt
from app.providers.models import DISPLAY_NAMES
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.scans.router import get_owned_scan, serialize as serialize_scan
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}", tags=["Analytics"])

METRIC_KEYS = ("mention_rate", "recommendation_rate", "share_of_voice", "citation_rate", "positive_sentiment_rate", "average_position")


def _engine_name(key: str | None) -> str:
    return DISPLAY_NAMES.get(key or "", key or "Unknown")


def _verdict(mentioned: bool, recommended: bool) -> str:
    return "recommended" if recommended else "mentioned" if mentioned else "absent"


def _snapshots(session, project_id) -> list[tuple[MetricSnapshot, Scan]]:
    return session.execute(
        select(MetricSnapshot, Scan).join(Scan, Scan.id == MetricSnapshot.scan_id)
        .where(MetricSnapshot.project_id == project_id).order_by(Scan.id)
    ).all()


def _latest_scan_id(session, project_id, scan_id: int | None) -> int | None:
    if scan_id is not None:
        return scan_id
    rows = _snapshots(session, project_id)
    return rows[-1].Scan.id if rows else None


def build_dashboard(session, project) -> dict:
    competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
    active_prompts = session.scalar(
        select(func.count()).select_from(Prompt).where(Prompt.project_id == project.id, Prompt.is_active)
    ) or 0
    latest_scan = session.scalar(select(Scan).where(Scan.project_id == project.id).order_by(Scan.id.desc()))
    history = _snapshots(session, project.id)

    base = {
        "project": {"id": str(project.id), "brand_name": project.brand_name, "website": project.website,
                    "category": project.category, "country": project.country},
        "counts": {"competitors": len(competitors), "active_prompts": active_prompts},
        "latest_scan": serialize_scan(latest_scan) if latest_scan else None,
    }
    if not history:
        return {**base, "has_data": False, "visibility": None, "engines": [], "competitors": [],
                "trend": [], "top_opportunities": [], "recent_answers": []}

    snapshot, scan = history[-1]
    previous = history[-2].MetricSnapshot if len(history) > 1 else None
    visibility = {k: getattr(snapshot, k) for k in METRIC_KEYS}
    visibility["total_responses"] = snapshot.total_responses
    visibility["deltas"] = {
        k: (round(getattr(snapshot, k) - getattr(previous, k), 4)
            if previous and getattr(snapshot, k) is not None and getattr(previous, k) is not None else None)
        for k in METRIC_KEYS
    }
    # Rates are measured on a sample of answers; say how much they can move by chance.
    rates = ("mention_rate", "recommendation_rate", "share_of_voice", "citation_rate")
    visibility["margins"] = {k: margin(getattr(snapshot, k), snapshot.total_responses) for k in rates}
    visibility["significant"] = {
        k: significant(getattr(previous, k), previous.total_responses, getattr(snapshot, k), snapshot.total_responses)
        if previous else None
        for k in rates
    }

    comp_metrics = {m.competitor_id: m for m in session.scalars(select(CompetitorMetric).where(CompetitorMetric.scan_id == scan.id))}
    brand_citations = session.scalar(
        select(func.count()).select_from(Citation).join(AIResponseRecord, AIResponseRecord.id == Citation.ai_response_id)
        .where(AIResponseRecord.scan_id == scan.id, Citation.is_brand_owned)
    ) or 0
    competitor_rows = [{
        "id": None, "name": project.brand_name, "is_you": True,
        "mention_rate": snapshot.mention_rate, "recommendation_rate": snapshot.recommendation_rate,
        "share_of_voice": snapshot.share_of_voice, "average_position": snapshot.average_position,
        "citation_count": brand_citations,
    }]
    for c in competitors:
        m = comp_metrics.get(c.id)
        if m:
            competitor_rows.append({
                "id": c.id, "name": c.name, "is_you": False, "mention_rate": m.mention_rate,
                "recommendation_rate": m.recommendation_rate, "share_of_voice": m.share_of_voice,
                "average_position": m.average_position, "citation_count": m.citation_count,
            })
    competitor_rows.sort(key=lambda r: r["mention_rate"], reverse=True)

    # Every tracked competitor per scan, so the dashboard can chart brands side by side.
    names = {c.id: c.name for c in competitors}
    competitor_trend: dict[int, dict] = defaultdict(dict)
    for cm in session.scalars(select(CompetitorMetric).where(CompetitorMetric.scan_id.in_([s.id for _, s in history]))):
        if cm.competitor_id in names:
            competitor_trend[cm.scan_id][names[cm.competitor_id]] = {
                k: getattr(cm, k) for k in ("mention_rate", "recommendation_rate", "share_of_voice")
            }

    opportunities = session.scalars(
        select(Opportunity).where(Opportunity.scan_id == scan.id, Opportunity.status.in_(("open", "in_progress")))
    ).all()
    opportunities = sorted(opportunities, key=lambda o: (IMPACT_ORDER.get(o.impact, 9), -o.confidence))[:5]

    recent = session.execute(
        select(AIResponseRecord, Mention).join(Mention, Mention.ai_response_id == AIResponseRecord.id)
        .where(AIResponseRecord.scan_id == scan.id).order_by(AIResponseRecord.id.desc()).limit(8)
    ).all()

    return {
        **base,
        "has_data": True,
        "metrics_scan": serialize_scan(scan),
        "visibility": visibility,
        "engines": [{"key": k, "name": _engine_name(k), **v} for k, v in snapshot.by_engine.items()],
        "competitors": competitor_rows,
        "trend": [{
            "scan_id": s.id, "date": s.completed_at or s.created_at,
            **{k: getattr(m, k) for k in ("mention_rate", "recommendation_rate", "share_of_voice")},
            "competitors": competitor_trend.get(s.id, {}),
        } for m, s in history],
        "top_opportunities": [serialize_opportunity(o) for o in opportunities],
        "recent_answers": [{
            "id": r.AIResponseRecord.id, "engine": r.AIResponseRecord.engine,
            "engine_name": _engine_name(r.AIResponseRecord.engine), "prompt": r.AIResponseRecord.prompt,
            "verdict": _verdict(r.Mention.mentioned, r.Mention.recommended), "position": r.Mention.position,
            "created_at": r.AIResponseRecord.created_at,
        } for r in recent],
    }


@router.get("/dashboard")
def dashboard(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        return build_dashboard(session, project)


@router.get("/scans/{scan_id}/results")
def scan_results(project_id: UUID, scan_id: int, current_user: User = Depends(get_current_user)):
    """Prompt-level view: what every engine said about you and who it recommended."""
    with SessionLocal() as session:
        scan = get_owned_scan(session, project_id, scan_id, current_user.id)
        names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
        grouped: dict[int, dict] = {}
        for o in load_observations(session, scan.id):
            row = grouped.setdefault(o.scan_prompt_id, {
                "scan_prompt_id": o.scan_prompt_id, "prompt_id": o.prompt_id, "text": o.prompt_text,
                "category": o.category, "engines": [],
            })
            row["engines"].append({
                "response_id": o.response_id, "engine": o.engine, "engine_name": _engine_name(o.engine),
                "verdict": _verdict(o.brand["mentioned"], o.brand["recommended"]),
                "position": o.brand["position"], "sentiment": o.brand["sentiment"],
                "competitors_recommended": [names[cid] for cid, v in o.competitors.items() if v.get("recommended") and cid in names],
                "citations": sorted({c["domain"] for c in o.citations if c["domain"]}),
            })
        rows = list(grouped.values())
        for row in rows:
            verdicts = [e["verdict"] for e in row["engines"]]
            row["seen_on"] = sum(v != "absent" for v in verdicts)
            row["recommended_on"] = sum(v == "recommended" for v in verdicts)
        return {"scan": serialize_scan(scan), "prompts": rows}


@router.get("/responses/{response_id}")
def response_detail(project_id: UUID, response_id: int, current_user: User = Depends(get_current_user)):
    """Observation and interpretation side by side (PRD section 100)."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        record = session.scalar(
            select(AIResponseRecord).join(Scan, Scan.id == AIResponseRecord.scan_id)
            .where(AIResponseRecord.id == response_id, Scan.project_id == project.id)
        )
        if not record:
            raise AppError(404, "RESPONSE_NOT_FOUND", "Response not found.")
        mention = session.scalar(select(Mention).where(Mention.ai_response_id == record.id))
        names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == project.id))}
        observations = session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id == record.id)).all()
        citations = session.scalars(select(Citation).where(Citation.ai_response_id == record.id)).all()
        return {
            "id": record.id, "scan_id": record.scan_id, "engine": record.engine, "engine_name": _engine_name(record.engine),
            "model": record.model, "provider": record.provider, "prompt": record.prompt, "text": record.response_text,
            "latency_ms": record.latency_ms, "created_at": record.created_at,
            "brand": {
                "name": project.brand_name, "mentioned": mention.mentioned, "recommended": mention.recommended,
                "position": mention.position, "sentiment": mention.sentiment, "reason": mention.reason,
                "evidence": mention.evidence,
                "method": mention.analysis_method,
            } if mention else None,
            "competitors": [{
                "id": o.competitor_id, "name": names.get(o.competitor_id), "mentioned": o.mentioned,
                "recommended": o.recommended, "position": o.position, "sentiment": o.sentiment,
                "reason": o.reason, "evidence": o.evidence,
            } for o in observations],
            "citations": [{"url": c.url, "domain": c.domain, "source_type": c.source_type,
                           "is_brand_owned": c.is_brand_owned, "competitor": names.get(c.competitor_id)} for c in citations],
        }


@router.get("/citations")
def citations(project_id: UUID, scan_id: int | None = None, current_user: User = Depends(get_current_user)):
    """Which sources AI leans on, and whether they appear alongside you or your competitors."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        target = _latest_scan_id(session, project.id, scan_id)
        if target is None:
            return {"scan_id": None, "sources": []}
        get_owned_scan(session, project_id, target, current_user.id)
        names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == project.id))}
        agg: dict[str, dict] = {}
        for o in load_observations(session, target):
            recommended_comps = {names[c] for c, v in o.competitors.items() if v.get("recommended") and c in names}
            for c in o.citations:
                if not c["domain"]:
                    continue
                row = agg.setdefault(c["domain"], {
                    "domain": c["domain"], "source_type": c["source_type"], "citations": 0,
                    "with_you": 0, "with_competitors": Counter(), "is_brand_owned": c["is_brand_owned"],
                    "owner": project.brand_name if c["is_brand_owned"] else names.get(c["competitor_id"]),
                    "urls": set(),
                })
                row["citations"] += 1
                row["urls"].add(c["url"])
                if o.brand["mentioned"]:
                    row["with_you"] += 1
                row["with_competitors"].update(recommended_comps)
        sources = sorted(agg.values(), key=lambda r: r["citations"], reverse=True)
        for r in sources:
            r["with_competitors"] = [{"name": n, "count": k} for n, k in r["with_competitors"].most_common()]
            r["urls"] = sorted(r["urls"])[:5]
            r["group"] = "both" if r["with_you"] and r["with_competitors"] else "you" if r["with_you"] else "competitors"
        return {"scan_id": target, "sources": sources}


@router.get("/competitors/analysis")
def competitor_analysis(project_id: UUID, scan_id: int | None = None, current_user: User = Depends(get_current_user)):
    """Prompt-level wins and losses against each competitor (PRD section 51)."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        target = _latest_scan_id(session, project.id, scan_id)
        competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
        if target is None:
            return {"scan_id": None, "competitors": []}
        get_owned_scan(session, project_id, target, current_user.id)
        per_prompt: dict[int, dict] = defaultdict(lambda: {"text": "", "you": False, "comps": set()})
        for o in load_observations(session, target):
            row = per_prompt[o.scan_prompt_id]
            row["text"] = o.prompt_text
            row["you"] = row["you"] or o.brand["recommended"]
            row["comps"] |= {cid for cid, v in o.competitors.items() if v.get("recommended")}
        metrics = {m.competitor_id: m for m in session.scalars(select(CompetitorMetric).where(CompetitorMetric.scan_id == target))}
        result = []
        for c in competitors:
            wins = [r["text"] for r in per_prompt.values() if r["you"] and c.id not in r["comps"]]
            losses = [r["text"] for r in per_prompt.values() if c.id in r["comps"] and not r["you"]]
            m = metrics.get(c.id)
            result.append({
                "id": c.id, "name": c.name, "website": c.website,
                "mention_rate": m.mention_rate if m else 0, "recommendation_rate": m.recommendation_rate if m else 0,
                "share_of_voice": m.share_of_voice if m else 0, "average_position": m.average_position if m else None,
                "you_win": len(wins), "they_win": len(losses),
                "both": sum(1 for r in per_prompt.values() if r["you"] and c.id in r["comps"]),
                "losing_prompts": sorted(losses)[:10], "winning_prompts": sorted(wins)[:10],
            })
        return {"scan_id": target, "total_prompts": len(per_prompt), "competitors": result}
