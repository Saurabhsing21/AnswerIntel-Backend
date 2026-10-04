"""Deterministic metrics (PRD sections 30-35). Methodology, kept stable across versions:

- Denominator for all rates = successful AI responses in the scan (prompt x engine).
- mention_rate = responses that name the brand / responses.
- recommendation_rate = responses that recommend the brand / responses.
- share_of_voice = brand recommendations / recommendations of brand + all competitors.
- average_position = mean rank over responses that ranked the brand in an explicit list.
- citation_rate = responses citing at least one brand-owned URL / responses.
- positive_sentiment_rate = positive mentions / mentions.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.models import Citation, CompetitorObservation, Mention
from app.competitors.models import Competitor
from app.metrics.models import CompetitorMetric, MetricSnapshot
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan


@dataclass
class Observation:
    response_id: int
    engine: str
    scan_prompt_id: int
    prompt_id: int | None
    prompt_text: str
    category: str
    brand: dict
    competitors: dict[int, dict] = field(default_factory=dict)
    citations: list[dict] = field(default_factory=list)


def load_observations(session: Session, scan_id: int) -> list[Observation]:
    rows = session.execute(
        select(AIResponseRecord, ScanPrompt, Mention)
        .join(ScanPrompt, ScanPrompt.id == AIResponseRecord.scan_prompt_id)
        .join(Mention, Mention.ai_response_id == AIResponseRecord.id)
        .where(AIResponseRecord.scan_id == scan_id)
        .order_by(AIResponseRecord.id)
    ).all()
    if not rows:
        return []
    ids = [r.AIResponseRecord.id for r in rows]
    comps: dict[int, dict[int, dict]] = defaultdict(dict)
    for o in session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id.in_(ids))):
        comps[o.ai_response_id][o.competitor_id] = {
            "mentioned": o.mentioned, "recommended": o.recommended, "position": o.position, "sentiment": o.sentiment,
        }
    cites: dict[int, list[dict]] = defaultdict(list)
    for c in session.scalars(select(Citation).where(Citation.ai_response_id.in_(ids))):
        cites[c.ai_response_id].append({
            "url": c.url, "domain": c.domain, "source_type": c.source_type,
            "is_brand_owned": c.is_brand_owned, "competitor_id": c.competitor_id,
        })
    return [
        Observation(
            response_id=r.AIResponseRecord.id,
            engine=r.AIResponseRecord.engine or r.AIResponseRecord.model,
            scan_prompt_id=r.ScanPrompt.id,
            prompt_id=r.ScanPrompt.prompt_id,
            prompt_text=r.ScanPrompt.text,
            category=r.ScanPrompt.category,
            brand={
                "mentioned": r.Mention.mentioned, "recommended": r.Mention.recommended,
                "position": r.Mention.position, "sentiment": r.Mention.sentiment,
            },
            competitors=comps[r.AIResponseRecord.id],
            citations=cites[r.AIResponseRecord.id],
        )
        for r in rows
    ]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def calculate(observations: list[Observation], competitor_ids: list[int]) -> dict:
    n = len(observations)
    brand_mentions = [o for o in observations if o.brand["mentioned"]]
    brand_recs = sum(o.brand["recommended"] for o in observations)
    comp_recs = {cid: sum(o.competitors.get(cid, {}).get("recommended", False) for o in observations) for cid in competitor_ids}
    total_recs = brand_recs + sum(comp_recs.values())

    by_engine: dict[str, dict] = {}
    for engine in sorted({o.engine for o in observations}):
        rows = [o for o in observations if o.engine == engine]
        by_engine[engine] = {
            "responses": len(rows),
            "mention_rate": _rate(sum(o.brand["mentioned"] for o in rows), len(rows)),
            "recommendation_rate": _rate(sum(o.brand["recommended"] for o in rows), len(rows)),
        }

    competitors = {}
    for cid in competitor_ids:
        obs = [o.competitors.get(cid, {}) for o in observations]
        competitors[cid] = {
            "mention_rate": _rate(sum(x.get("mentioned", False) for x in obs), n),
            "recommendation_rate": _rate(comp_recs[cid], n),
            "share_of_voice": _rate(comp_recs[cid], total_recs),
            "average_position": _avg([x["position"] for x in obs if x.get("position")]),
            "citation_count": sum(1 for o in observations for c in o.citations if c["competitor_id"] == cid),
        }

    return {
        "total_responses": n,
        "mention_rate": _rate(len(brand_mentions), n),
        "recommendation_rate": _rate(brand_recs, n),
        "share_of_voice": _rate(brand_recs, total_recs),
        "average_position": _avg([o.brand["position"] for o in observations if o.brand["position"]]),
        "citation_rate": _rate(sum(any(c["is_brand_owned"] for c in o.citations) for o in observations), n),
        "positive_sentiment_rate": _rate(sum(o.brand["sentiment"] == "positive" for o in brand_mentions), len(brand_mentions)),
        "by_engine": by_engine,
        "competitors": competitors,
    }


def compute_and_store(session: Session, scan: Scan) -> dict:
    competitor_ids = list(session.scalars(select(Competitor.id).where(Competitor.project_id == scan.project_id)))
    observations = load_observations(session, scan.id)
    metrics = calculate(observations, competitor_ids)

    session.execute(delete(MetricSnapshot).where(MetricSnapshot.scan_id == scan.id))
    session.execute(delete(CompetitorMetric).where(CompetitorMetric.scan_id == scan.id))
    session.add(MetricSnapshot(
        project_id=scan.project_id,
        scan_id=scan.id,
        **{k: metrics[k] for k in (
            "total_responses", "mention_rate", "recommendation_rate", "share_of_voice",
            "citation_rate", "positive_sentiment_rate", "average_position", "by_engine",
        )},
    ))
    for cid, m in metrics["competitors"].items():
        session.add(CompetitorMetric(scan_id=scan.id, competitor_id=cid, **m))
    session.flush()
    return {"metrics": metrics, "observations": observations}
