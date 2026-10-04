"""Opportunity engine (PRD sections 36-40): deterministic rules over stored
observations. Every opportunity carries the evidence that produced it."""

from collections import Counter, defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.competitors.models import Competitor
from app.metrics.service import Observation
from app.opportunities.models import Opportunity
from app.scans.models import Scan

IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
CATEGORY_LABELS = {
    "CATEGORY": "category discovery",
    "COMPARISON": "comparison",
    "ALTERNATIVE": "alternatives",
    "USE_CASE": "use-case",
    "PROBLEM": "problem-solving",
    "BUYER_INTENT": "buyer-intent",
    "COMPETITOR": "competitor",
}


def _impact(count: int, total: int) -> str:
    share = count / total if total else 0
    if count >= 5 or share >= 0.3:
        return "high"
    if count >= 2 or share >= 0.1:
        return "medium"
    return "low"


def _confidence(evidence_count: int) -> float:
    return round(min(0.95, 0.5 + 0.06 * evidence_count), 2)


def detect(observations: list[Observation], brand: str, competitors: dict[int, str]) -> list[dict]:
    found: list[dict] = []
    prompts = {o.scan_prompt_id: o.prompt_text for o in observations}
    total_prompts = len(prompts)

    # COMPETITOR_GAP: a competitor is recommended on prompts where the brand is absent.
    for cid, name in competitors.items():
        lost = sorted({
            o.prompt_text for o in observations
            if o.competitors.get(cid, {}).get("recommended") and not o.brand["mentioned"]
        })
        if lost:
            found.append({
                "type": "COMPETITOR_GAP",
                "title": f"{name} is recommended on {len(lost)} prompt{'s' if len(lost) > 1 else ''} where you are absent",
                "description": f"AI engines recommend {name} but do not mention {brand} at all on these buyer questions.",
                "recommended_action": f"Publish pages that answer these exact questions and position {brand} against {name}.",
                "impact": _impact(len(lost), total_prompts),
                "confidence": _confidence(len(lost)),
                "evidence": {"competitor": name, "prompts": lost[:10]},
            })

    # CITATION_GAP: third-party sources that show up where competitors win, but never where you win.
    comp_domains: Counter = Counter()
    brand_domains: set[str] = set()
    for o in observations:
        third_party = {c["domain"] for c in o.citations if c["domain"] and not c["is_brand_owned"] and not c["competitor_id"]}
        if o.brand["mentioned"]:
            brand_domains |= third_party
        elif any(v.get("recommended") for v in o.competitors.values()):
            comp_domains.update(third_party)
    missing = [(d, n) for d, n in comp_domains.most_common() if d not in brand_domains and n >= 2]
    if missing:
        found.append({
            "type": "CITATION_GAP",
            "title": f"{len(missing)} source{'s' if len(missing) > 1 else ''} AI cites for competitors never cite you",
            "description": "These sites are repeatedly cited in answers that recommend your competitors and never in answers that mention you.",
            "recommended_action": "Get listed, reviewed, or mentioned on these sources, starting with the most cited.",
            "impact": _impact(sum(n for _, n in missing), len(observations)),
            "confidence": _confidence(sum(n for _, n in missing)),
            "evidence": {"domains": [{"domain": d, "citations": n} for d, n in missing[:8]]},
        })

    # CONTENT_GAP: whole prompt categories where the brand never appears.
    by_category: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_category[o.category].append(o)
    for category, rows in sorted(by_category.items()):
        category_prompts = {o.scan_prompt_id for o in rows}
        if len(category_prompts) >= 2 and not any(o.brand["mentioned"] for o in rows):
            label = CATEGORY_LABELS.get(category, category.lower())
            found.append({
                "type": "CONTENT_GAP",
                "title": f"You are invisible on {label} questions",
                "description": f"{brand} was not mentioned in any answer to {len(category_prompts)} {label} prompts.",
                "recommended_action": f"Create content that directly answers {label} questions for your category.",
                "impact": _impact(len(category_prompts), total_prompts),
                "confidence": _confidence(len(rows)),
                "evidence": {"category": category, "prompts": sorted({o.prompt_text for o in rows})[:10]},
            })

    # POSITIONING_GAP: mentioned often, recommended rarely.
    mentioned = [o for o in observations if o.brand["mentioned"]]
    not_recommended = [o for o in mentioned if not o.brand["recommended"]]
    if len(mentioned) >= 3 and len(not_recommended) / len(mentioned) >= 0.5:
        found.append({
            "type": "POSITIONING_GAP",
            "title": "AI mentions you but rarely recommends you",
            "description": f"{brand} was mentioned in {len(mentioned)} answers but only recommended in {len(mentioned) - len(not_recommended)}.",
            "recommended_action": "Sharpen who you are for and why, on your homepage and in third-party profiles, so AI can recommend you with confidence.",
            "impact": "high" if len(not_recommended) >= 5 else "medium",
            "confidence": _confidence(len(mentioned)),
            "evidence": {"prompts": sorted({o.prompt_text for o in not_recommended})[:10]},
        })

    # COMPARISON_GAP: losing head-to-head comparison prompts.
    lost_comparisons = sorted({
        o.prompt_text for o in observations
        if o.category in ("COMPARISON", "COMPETITOR")
        and not o.brand["recommended"]
        and any(v.get("recommended") for v in o.competitors.values())
    })
    if lost_comparisons:
        found.append({
            "type": "COMPARISON_GAP",
            "title": f"You lose {len(lost_comparisons)} comparison prompt{'s' if len(lost_comparisons) > 1 else ''}",
            "description": "When buyers compare options directly, AI picks a competitor over you.",
            "recommended_action": "Publish honest comparison and alternatives pages with feature tables AI can quote.",
            "impact": _impact(len(lost_comparisons), total_prompts),
            "confidence": _confidence(len(lost_comparisons)),
            "evidence": {"prompts": lost_comparisons[:10]},
        })

    def weight(x: dict) -> int:
        ev = x["evidence"]
        return len(ev.get("prompts") or ev.get("domains") or [])

    return sorted(found, key=lambda x: (IMPACT_ORDER[x["impact"]], -weight(x), -x["confidence"]))


def generate_and_store(session: Session, scan: Scan, brand: str, observations: list[Observation]) -> list[Opportunity]:
    competitors = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
    session.execute(delete(Opportunity).where(Opportunity.scan_id == scan.id))
    rows = [Opportunity(project_id=scan.project_id, scan_id=scan.id, **item) for item in detect(observations, brand, competitors)]
    session.add_all(rows)
    session.flush()
    return rows
