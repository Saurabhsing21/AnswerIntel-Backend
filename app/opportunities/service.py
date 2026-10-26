"""Opportunity engine (PRD sections 36-40): deterministic rules over stored
observations. Every opportunity carries the evidence that produced it."""

import re
from collections import Counter, defaultdict

from sqlalchemy import delete, func, select
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


# Action Center grouping (PRD 11): where the founder has to do the work.
AREAS = {
    "CONTENT_GAP": "content",
    "COMPETITOR_GAP": "content",
    "COMPARISON_GAP": "content",
    "CITATION_GAP": "third_party",
    "POSITIONING_GAP": "positioning",
    "ENTITY_GAP": "positioning",
    "TECHNICAL_GAP": "technical",
}
OBJECTIVES = {
    "CONTENT_GAP": "Get mentioned on the question types where you are invisible today.",
    "COMPETITOR_GAP": "Appear in the answers where this competitor is recommended instead of you.",
    "COMPARISON_GAP": "Win the head-to-head comparison prompts against your competitors.",
    "CITATION_GAP": "Be cited by the sources AI already trusts for your category.",
    "POSITIONING_GAP": "Move from being mentioned to being recommended.",
    "ENTITY_GAP": "Be named on open category questions, not only when buyers search for you by name.",
    "TECHNICAL_GAP": "Make sure AI crawlers can read and quote your website.",
}
# The title names the top finding, so a minor gap never reads like a serious one.
TECHNICAL_TITLES = {
    "ROBOTS_BLOCKS_AI": "Your robots.txt blocks AI crawlers",
    "THIN_CONTENT": "Your homepage is hard for AI to read",
    "NO_STRUCTURED_DATA": "Your homepage has no structured data for AI",
    "NO_LLMS_TXT": "Your site has no llms.txt for AI",
}
DISCOVERY_CATEGORIES = ("CATEGORY", "USE_CASE", "PROBLEM")
BRANDED_CATEGORIES = ("COMPARISON", "COMPETITOR", "ALTERNATIVE")


def _impact(count: int, total: int) -> str:
    share = count / total if total else 0
    if count >= 5 or share >= 0.3:
        return "high"
    if count >= 2 or share >= 0.1:
        return "medium"
    return "low"


def _confidence(evidence_count: int) -> float:
    return round(min(0.95, 0.5 + 0.06 * evidence_count), 2)


def detect(
    observations: list[Observation], brand: str, competitors: dict[int, str], audit: dict | None = None
) -> list[dict]:
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

    # ENTITY_GAP: known by name, but not associated with the category on open questions (PRD 10, type 4).
    discovery = [o for o in observations if o.category in DISCOVERY_CATEGORIES]
    branded = [o for o in observations if o.category in BRANDED_CATEGORIES]
    if len({o.scan_prompt_id for o in discovery}) >= 3 and len({o.scan_prompt_id for o in branded}) >= 2:
        discovery_rate = round(sum(o.brand["mentioned"] for o in discovery) / len(discovery), 4)
        branded_rate = round(sum(o.brand["mentioned"] for o in branded) / len(branded), 4)
        if discovery_rate < 0.35 and branded_rate - discovery_rate >= 0.3:
            missed = sorted({o.prompt_text for o in discovery if not o.brand["mentioned"]})
            found.append({
                "type": "ENTITY_GAP",
                "title": "AI knows your name but not your category",
                "description": (
                    f"{brand} appears in {round(branded_rate * 100)}% of answers when buyers name it, "
                    f"but only {round(discovery_rate * 100)}% when they ask open category or use-case questions."
                ),
                "recommended_action": (
                    "State what you are and who you are for in one sentence, then repeat it across your homepage title, "
                    "headings and third-party profiles so AI links your name to the category."
                ),
                "impact": _impact(len(missed), total_prompts),
                "confidence": _confidence(len(discovery) + len(branded)),
                "evidence": {"discovery_rate": discovery_rate, "branded_rate": branded_rate, "prompts": missed[:10]},
            })

    # TECHNICAL_GAP: AI crawlers cannot reach or read the website (PRD 10, type 6). Facts from the site audit.
    if audit and audit["findings"]:
        order = {"high": 0, "medium": 1, "low": 2}
        findings = sorted(audit["findings"], key=lambda f: order[f["impact"]])
        found.append({
            "type": "TECHNICAL_GAP",
            "title": TECHNICAL_TITLES[findings[0]["code"]],
            "description": " ".join(f["message"] for f in findings),
            "recommended_action": " ".join(f["action"] for f in findings),
            "impact": findings[0]["impact"],
            "confidence": 0.9,  # observed directly on the site, not inferred from answers
            "evidence": {"url": audit["url"], "findings": findings},
        })

    _add_steps(found, observations, brand, competitors)
    for item in found:
        item["evidence"]["expected_objective"] = OBJECTIVES[item["type"]]

    def weight(x: dict) -> int:
        ev = x["evidence"]
        return len(ev.get("prompts") or ev.get("domains") or [])

    return sorted(found, key=lambda x: (IMPACT_ORDER[x["impact"]], -weight(x), -x["confidence"]))


EFFORT = {"TECHNICAL_GAP": "S", "POSITIONING_GAP": "S", "ENTITY_GAP": "M", "CITATION_GAP": "M",
          "COMPARISON_GAP": "M", "COMPETITOR_GAP": "M", "CONTENT_GAP": "L"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _domains_behind(observations: list[Observation], winner) -> list[str]:
    """Third-party domains cited in answers that `winner(o)` says the brand lost, most cited first."""
    counts: Counter = Counter()
    for o in observations:
        if winner(o):
            counts.update({c["domain"] for c in o.citations if c["domain"] and not c["is_brand_owned"] and not c["competitor_id"]})
    return [d for d, _ in counts.most_common(3)]


def _add_steps(found: list[dict], observations: list[Observation], brand: str, competitors: dict[int, str]) -> None:
    """Concrete, checkable steps for each opportunity, named from the evidence: exact pages, exact domains."""
    ids = {name: cid for cid, name in competitors.items()}
    for item in found:
        ev, kind = item["evidence"], item["type"]
        prompts = ev.get("prompts") or []
        steps: list[str] = []
        if kind == "COMPETITOR_GAP":
            name = ev["competitor"]
            cid = ids.get(name)
            steps.append(f"Publish a comparison page at /{_slug(brand)}-vs-{_slug(name)} with an honest feature and price table.")
            if prompts:
                steps.append(f'Answer "{prompts[0]}" in the first paragraph of that page, in one clear sentence.')
            domains = _domains_behind(observations, lambda o: o.competitors.get(cid, {}).get("recommended") and not o.brand["mentioned"])
            if domains:
                steps.append(f"Get listed or reviewed on {', '.join(domains)}: AI cites them when it recommends {name}.")
        elif kind == "COMPARISON_GAP":
            for cid, name in list(competitors.items())[:3]:
                steps.append(f"Publish /{_slug(brand)}-vs-{_slug(name)}: who each is best for, a feature table, pricing.")
            steps.append(f"Publish /{_slug(brand)}-alternatives that lists you alongside your competitors.")
        elif kind == "CITATION_GAP":
            for d in ev.get("domains", [])[:4]:
                steps.append(f"Get {brand} listed on {d['domain']}: ask for a review, submit a listing, or pitch the author ({d['citations']} citations).")
        elif kind == "CONTENT_GAP":
            for q in prompts[:3]:
                steps.append(f'Publish a page that answers "{q}" directly, with a short verdict near the top.')
            steps.append("Link these pages from your homepage and navigation so crawlers find them.")
        elif kind == "POSITIONING_GAP":
            steps.append(f'Put one sentence at the top of your homepage: "{brand} is the best <category> for <audience> because <reason>."')
            steps.append("Add proof AI can quote: customer count, a named customer, and one measurable result.")
            steps.append("Use the same sentence on G2, Capterra, LinkedIn and Crunchbase.")
        elif kind == "ENTITY_GAP":
            steps.append(f"Use one description of what {brand} is, word for word, in your homepage title, meta description and H1.")
            steps.append("Copy that description to LinkedIn, Crunchbase, G2 and Wikidata so AI links your name to the category.")
        elif kind == "TECHNICAL_GAP":
            steps.extend(f["action"] for f in ev.get("findings", []))
        ev["steps"] = steps
        ev["effort"] = EFFORT[kind]


EFFORT_ORDER = {"S": 0, "M": 1, "L": 2}


def weekly_plan(rows: list[Opportunity]) -> list[Opportunity]:
    """This week's 3 actions: the biggest gaps first, quick wins before big projects. Done ones stay, to show progress."""
    live = [o for o in rows if o.trend != "resolved" and o.status != "dismissed"]
    return sorted(live, key=lambda o: (IMPACT_ORDER[o.impact], EFFORT_ORDER.get(o.evidence.get("effort"), 1), -o.confidence))[:3]


def fingerprint(item: dict) -> str:
    """Identity of a gap across scans: its type plus what it is about (a competitor, a prompt category)."""
    ev = item["evidence"]
    return f"{item['type']}:{ev.get('competitor') or ev.get('category') or ''}".lower()


def _weight(evidence: dict) -> int:
    return len(evidence.get("prompts") or evidence.get("domains") or evidence.get("findings") or [])


def generate_and_store(
    session: Session, scan: Scan, brand: str, observations: list[Observation], audit: dict | None = None
) -> list[Opportunity]:
    """Stores this scan's opportunities, carrying each one's status and history from the previous scan.
    Gaps that disappeared are stored as "resolved", so the user sees what their work fixed."""
    competitors = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
    session.execute(delete(Opportunity).where(Opportunity.scan_id == scan.id))
    previous_scan = session.scalar(
        select(func.max(Opportunity.scan_id)).where(Opportunity.project_id == scan.project_id, Opportunity.scan_id < scan.id)
    )
    previous = {
        o.fingerprint: o
        for o in session.scalars(select(Opportunity).where(Opportunity.scan_id == previous_scan, Opportunity.trend != "resolved"))
    } if previous_scan else {}

    rows = []
    for item in detect(observations, brand, competitors, audit):
        fp = fingerprint(item)
        old = previous.pop(fp, None)
        row = Opportunity(project_id=scan.project_id, scan_id=scan.id, fingerprint=fp, **item)
        if old is None:
            row.trend, row.first_seen_scan_id = "new", scan.id
        else:
            before, now = _weight(old.evidence), _weight(item["evidence"])
            worse = IMPACT_ORDER[item["impact"]] < IMPACT_ORDER[old.impact] or now > before
            better = IMPACT_ORDER[item["impact"]] > IMPACT_ORDER[old.impact] or now < before
            row.trend = "worse" if worse else "better" if better else "open"
            row.status = "open" if old.status == "completed" else old.status  # marked done but still there: back on the list
            row.first_seen_scan_id = old.first_seen_scan_id or old.scan_id
            row.experiment_id = old.experiment_id
            row.evidence = {**item["evidence"], "previous_count": before,
                            **({"retest": old.evidence["retest"]} if "retest" in old.evidence else {})}
        rows.append(row)
    for fp, old in previous.items():  # gone this scan: fixed
        rows.append(Opportunity(
            project_id=scan.project_id, scan_id=scan.id, fingerprint=fp, type=old.type, title=old.title,
            description=old.description, recommended_action=old.recommended_action, impact=old.impact,
            confidence=old.confidence, evidence=old.evidence, trend="resolved",
            status="dismissed" if old.status == "dismissed" else "completed",
            first_seen_scan_id=old.first_seen_scan_id or old.scan_id, experiment_id=old.experiment_id,
        ))
    session.add_all(rows)
    session.flush()
    return rows
