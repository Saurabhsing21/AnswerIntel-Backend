"""Opportunity engine (PRD sections 36-40): deterministic rules over stored
observations. Every opportunity carries the evidence that produced it."""

import re
from collections import Counter, defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.analysis.heuristic import name_pattern
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
    "UNTRACKED_COMPETITOR": "positioning",
}
OBJECTIVES = {
    "CONTENT_GAP": "Get mentioned on the question types where you are invisible today.",
    "COMPETITOR_GAP": "Appear in the answers where competitors are recommended instead of you.",
    "COMPARISON_GAP": "Win the head-to-head comparison questions against your competitors.",
    "CITATION_GAP": "Be cited by the sources AI already trusts for your category.",
    "POSITIONING_GAP": "Move from being mentioned to being recommended.",
    "ENTITY_GAP": "Be named on open category questions, not only when buyers search for you by name.",
    "TECHNICAL_GAP": "Make sure AI crawlers can read and quote your website.",
    "UNTRACKED_COMPETITOR": "Track every brand AI recommends instead of you, so no loss goes unseen.",
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
COMPARISON_CATEGORIES = ("COMPARISON", "COMPETITOR")
SWITCH_CATEGORIES = ("ALTERNATIVE", "COMPETITOR")  # "alternatives to {brand}" cannot be won by naming the brand


def _impact(share: float) -> str:
    """Impact from the share of the scan's answers affected, so a gap is sized against the whole picture."""
    if share >= 0.2:
        return "high"
    if share >= 0.06:
        return "medium"
    return "low"


def _confidence(evidence_count: int) -> float:
    return round(min(0.95, 0.5 + 0.06 * evidence_count), 2)


def _third_party(o: Observation) -> set[str]:
    return {c["domain"] for c in o.citations if c["domain"] and not c["is_brand_owned"] and not c["competitor_id"]}


def unwinnable(o: Observation, brand: str) -> bool:
    """'Alternatives to {brand}' asks AI to name someone else: not naming the brand there is not a loss."""
    return o.category in SWITCH_CATEGORIES and bool(name_pattern(brand).search(o.prompt_text))


def _lost(o: Observation) -> bool:
    """An answer the brand lost: a tracked competitor is recommended there. Comparison answers are lost when the
    brand is not recommended; elsewhere, when it is not named at all."""
    if not any(v.get("recommended") for v in o.competitors.values()):
        return False
    return not o.brand["recommended"] if o.category in COMPARISON_CATEGORIES else not o.brand["mentioned"]


def _question_rows(rows: list[Observation], competitors: dict[int, str], lost=_lost) -> list[dict]:
    """One entry per question: how many engines it was lost on, and every competitor AI picked there, with its reason."""
    by_question: dict[int, list[Observation]] = defaultdict(list)
    for o in rows:
        by_question[o.scan_prompt_id].append(o)
    out = []
    for answers in by_question.values():
        lost_answers = [o for o in answers if lost(o)]
        if not lost_answers:
            continue
        winners: dict[int, dict] = {}
        domains: Counter = Counter()
        for o in lost_answers:
            domains.update(_third_party(o))
            for cid, v in o.competitors.items():
                if not v.get("recommended") or cid not in competitors:
                    continue
                w = winners.setdefault(cid, {"name": competitors[cid], "engines": 0, "reasons": Counter(), "quote": None})
                w["engines"] += 1
                if (v.get("reason") or "").strip():
                    w["reasons"][v["reason"].strip().rstrip(".")] += 1
                w["quote"] = w["quote"] or ((v.get("evidence") or "").strip() or None)
        out.append({
            "text": answers[0].prompt_text,
            "category": answers[0].category,
            "engines_lost": len(lost_answers),
            "engines_total": len(answers),
            "winners": [
                {"name": w["name"], "engines": w["engines"],
                 "reason": w["reasons"].most_common(1)[0][0] if w["reasons"] else None, "quote": w["quote"]}
                for w in sorted(winners.values(), key=lambda w: (-w["engines"], w["name"]))
            ],
            "cited_domains": [d for d, _ in domains.most_common(5)],
        })
    return sorted(out, key=lambda q: (-q["engines_lost"], q["text"]))


def _why(questions: list[dict], brand: str) -> list[str]:
    """2-4 sentences on why AI picked others, from the reasons it gave (most frequent first)."""
    reasons: Counter = Counter()
    for q in questions:
        for w in q["winners"]:
            if w["reason"]:
                reasons[(w["name"], w["reason"])] += w["engines"]
    why = [
        f"AI picked {name}: \"{reason}\" ({n} answer{'s' if n != 1 else ''})."
        for (name, reason), n in reasons.most_common(3)
    ]
    lost = sum(q["engines_lost"] for q in questions)
    total = sum(q["engines_total"] for q in questions)
    why.append(f"{brand} was left out of {lost} of {total} answers to these questions.")
    domains = Counter(d for q in questions for d in q["cited_domains"])
    if len(why) < 4 and domains:
        why.append(f"The answers relied on {', '.join(d for d, _ in domains.most_common(3))}, where {brand} does not show up.")
    if len(why) < 2:
        winners = Counter(w["name"] for q in questions for w in q["winners"])
        why.append(f"AI recommended {', '.join(n for n, _ in winners.most_common(3))} instead, without giving a reason.")
    return why[:4]


# Topics a founder can act on, spotted in the question or in the reasons AI gave for a competitor.
TOPICS = [
    (re.compile(r"support|customer (service|care)|help ?desk|complain|grievance", re.I),
     "Publish a customer support page listing every channel (phone, chat, email, in-app), hours, and the response time you commit to."),
    (re.compile(r"price|pricing|fee|charge|cost|cheap|brokerage|afford", re.I),
     "Publish a plain pricing page: every fee in one table, with a worked example of what a typical customer pays."),
    (re.compile(r"beginner|easy|simple|first[- ]time|new to|interface|user[- ]friendly", re.I),
     "Publish a beginner's guide that walks a first-time user through sign-up to first use, with screenshots."),
    (re.compile(r"document|docs|guide|tutorial|learn|educat|research|tools", re.I),
     "Publish learning resources (guides, tutorials, glossary) on your site and link them from your homepage."),
    (re.compile(r"safe|secur|trust|regulat|licen|compliance|fraud", re.I),
     "Publish a trust page with your licences, regulators, security practices and how customer money is protected."),
    (re.compile(r"review|rating|reputation|popular|largest|users", re.I),
     "Show proof AI can quote on your homepage: customer count, ratings with their source, and a named customer result."),
]


def _steps(kind: str, category: str, questions: list[dict], brand: str, competitors: dict[int, str]) -> list[str]:
    """5-8 steps tailored to the question type and to the reasons AI gave. Every page step names the questions it answers."""
    texts = [q["text"] for q in questions]
    quoted = "; ".join(f'"{t}"' for t in texts[:3])
    winners = Counter()
    for q in questions:
        for w in q["winners"]:
            winners[w["name"]] += w["engines"]
    steps: list[str] = []
    if category in COMPARISON_CATEGORIES:
        for name, _ in winners.most_common(3):
            theirs = "; ".join([f'"{q["text"]}"' for q in questions if any(w["name"] == name for w in q["winners"])][:2])
            steps.append(f"Publish /{_slug(brand)}-vs-{_slug(name)}: who each is best for, a feature table and pricing, answering {theirs}.")
    elif category == "ALTERNATIVE":
        named = sorted({n for t in texts for n in competitors.values() if name_pattern(n).search(t)})
        for name in named[:3]:
            steps.append(f"Publish /alternatives-to-{_slug(name)} explaining who should switch to {brand} and why, with a feature table.")
        if not named:
            steps.append(f"Publish an alternatives page that answers {quoted}, listing {brand} with a clear reason to pick it.")
    else:
        label = CATEGORY_LABELS.get(category, category.lower())
        steps.append(f"Publish one {label} guide that answers {quoted} directly, with a short verdict naming {brand} near the top.")

    reasons = " ".join(w["reason"] or "" for q in questions for w in q["winners"])
    for pattern, step in TOPICS:
        if pattern.search(" ".join(texts)) or pattern.search(reasons):
            steps.append(step)
    seen_reasons = set()
    for q in questions:
        for w in q["winners"]:
            if w["reason"] and w["reason"] not in seen_reasons and len(seen_reasons) < 2:
                seen_reasons.add(w["reason"])
                steps.append(f'AI credits {w["name"]} for "{w["reason"]}": show, with specifics, how {brand} does this on the new page.')
    domains = Counter(d for q in questions for d in q["cited_domains"])
    if domains:
        steps.append(f"Get {brand} listed or reviewed on {', '.join(d for d, _ in domains.most_common(3))}: AI cited them in these answers.")
    steps.append(f"Add an FAQ block to the new page(s) with each question as a heading and a two-sentence answer naming {brand}, marked up as FAQPage JSON-LD.")
    steps.append("Link the new page(s) from your homepage and main navigation so AI crawlers find it.")
    if len(steps) < 5:
        steps.append(f"Use the same one-line description of {brand} on your homepage, LinkedIn and review profiles.")
    return list(dict.fromkeys(steps))[:8]


def _success_metric(questions: list[dict], brand: str, engines: int) -> str:
    need = max(1, (engines * 2 + 2) // 3)
    n = len(questions)
    return f"Re-test {'this question' if n == 1 else f'these {n} questions'}: AI should name {brand} in at least {need} of {engines} engines."


def _question_gap(kind: str, category: str, questions: list[dict], brand: str, competitors: dict[int, str],
                  total_answers: int, engines: int, title: str, description: str, action: str) -> dict:
    lost = sum(q["engines_lost"] for q in questions)
    return {
        "type": kind, "title": title, "description": description, "recommended_action": action,
        "impact": _impact(lost / total_answers if total_answers else 0),
        "confidence": _confidence(lost),
        "evidence": {
            "category": category, "prompts": [q["text"] for q in questions][:10], "questions": questions,
            "answers_lost": lost, "why": _why(questions, brand),
            "steps": _steps(kind, category, questions, brand, competitors),
            "success_metric": _success_metric(questions, brand, engines),
        },
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def switching(observations: list[Observation], brand: str, competitors: dict[int, str]) -> list[dict]:
    """'Alternatives to {brand}' answers: where your customers would switch. Evidence, never a loss."""
    rows = [o for o in observations if unwinnable(o, brand)]
    return _question_rows(rows, competitors, lost=lambda o: any(v.get("recommended") for v in o.competitors.values()))


def detect(
    observations: list[Observation], brand: str, competitors: dict[int, str], audit: dict | None = None
) -> list[dict]:
    found: list[dict] = []
    prompts = {o.scan_prompt_id: o.prompt_text for o in observations}
    total_prompts = len(prompts)
    total_answers = len(observations)
    engines = len({o.engine for o in observations}) or 1
    winnable = [o for o in observations if not unwinnable(o, brand)]

    by_category: dict[str, list[Observation]] = defaultdict(list)
    for o in winnable:
        by_category[o.category].append(o)

    # CONTENT_GAP: whole question categories where the brand never appears. Its questions are not repeated below.
    invisible = set()
    for category, rows in sorted(by_category.items()):
        if category in COMPARISON_CATEGORIES:
            continue
        if len({o.scan_prompt_id for o in rows}) >= 2 and not any(o.brand["mentioned"] for o in rows):
            invisible.add(category)
            label = CATEGORY_LABELS.get(category, category.lower())
            questions = _question_rows(rows, competitors, lost=lambda o: not o.brand["mentioned"])
            found.append(_question_gap(
                "CONTENT_GAP", category, questions, brand, competitors, total_answers, engines,
                f"You are invisible on {label} questions",
                f"{brand} was not mentioned in any answer to {_plural(len(questions), label + ' question')}.",
                f"Create content that directly answers these {label} questions and names {brand}.",
            ))

    # COMPETITOR_GAP / COMPARISON_GAP: lost answers grouped by question type, each question once, every winner listed.
    for category, rows in sorted(by_category.items()):
        if category in invisible:
            continue
        questions = _question_rows(rows, competitors)
        if not questions:
            continue
        lost = sum(q["engines_lost"] for q in questions)
        names = Counter(w["name"] for q in questions for w in q["winners"])
        rivals = ", ".join(n for n, _ in names.most_common(3))
        label = CATEGORY_LABELS.get(category, category.lower())
        if category in COMPARISON_CATEGORIES:
            found.append(_question_gap(
                "COMPARISON_GAP", category, questions, brand, competitors, total_answers, engines,
                f"You lose {_plural(len(questions), label + ' question')} to {rivals}",
                f"When buyers compare options directly, AI picked {rivals} over {brand} in {_plural(lost, 'answer')}.",
                "Publish honest comparison pages with feature tables AI can quote.",
            ))
        else:
            found.append(_question_gap(
                "COMPETITOR_GAP", category, questions, brand, competitors, total_answers, engines,
                f"{rivals} {'is' if len(names) == 1 else 'are'} recommended instead of you on {_plural(len(questions), label + ' question')}",
                f"AI recommended {rivals} and left {brand} out of {_plural(lost, 'answer')} to {'this question' if len(questions) == 1 else 'these questions'}.",
                f"Publish content that answers these exact questions and gives AI a reason to name {brand}.",
            ))

    # CITATION_GAP: third-party sources that show up where competitors win, but never where you win.
    comp_domains: Counter = Counter()
    brand_domains: set[str] = set()
    for o in winnable:
        third_party = _third_party(o)
        if o.brand["mentioned"]:
            brand_domains |= third_party
        elif any(v.get("recommended") for v in o.competitors.values()):
            comp_domains.update(third_party)
    missing = [(d, n) for d, n in comp_domains.most_common() if d not in brand_domains and n >= 2]
    if missing:
        found.append({
            "type": "CITATION_GAP",
            "title": f"{_plural(len(missing), 'source')} AI cites for competitors never cite{'s' if len(missing) == 1 else ''} you",
            "description": "These sites are repeatedly cited in answers that recommend your competitors and never in answers that mention you.",
            "recommended_action": "Get listed, reviewed, or mentioned on these sources, starting with the most cited.",
            "impact": _impact(sum(n for _, n in missing) / total_answers if total_answers else 0),
            "confidence": _confidence(sum(n for _, n in missing)),
            "evidence": {"domains": [{"domain": d, "citations": n} for d, n in missing[:8]]},
        })

    # POSITIONING_GAP: mentioned often, recommended rarely.
    mentioned = [o for o in winnable if o.brand["mentioned"]]
    not_recommended = [o for o in mentioned if not o.brand["recommended"]]
    if len(mentioned) >= 3 and len(not_recommended) / len(mentioned) >= 0.5:
        found.append({
            "type": "POSITIONING_GAP",
            "title": "AI mentions you but rarely recommends you",
            "description": f"{brand} was mentioned in {len(mentioned)} answers but only recommended in {len(mentioned) - len(not_recommended)}.",
            "recommended_action": "Sharpen who you are for and why, on your homepage and in third-party profiles, so AI can recommend you with confidence.",
            "impact": _impact(len(not_recommended) / total_answers),
            "confidence": _confidence(len(mentioned)),
            "evidence": {"prompts": sorted({o.prompt_text for o in not_recommended})[:10]},
        })

    # ENTITY_GAP: known by name, but not associated with the category on open questions (PRD 10, type 4).
    discovery = [o for o in winnable if o.category in DISCOVERY_CATEGORIES]
    branded = [o for o in winnable if o.category in BRANDED_CATEGORIES]
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
                "impact": _impact(len(missed) / total_prompts if total_prompts else 0),
                "confidence": _confidence(len(discovery) + len(branded)),
                "evidence": {"discovery_rate": discovery_rate, "branded_rate": branded_rate, "prompts": missed[:10]},
            })

    # UNTRACKED_COMPETITOR: brands AI recommends that the project does not track yet.
    tracked = {n.lower() for n in competitors.values()} | {brand.lower()}
    untracked: dict[str, dict] = {}
    for o in observations:
        for name in dict.fromkeys(o.other_brands):
            if name.lower() in tracked:
                continue
            row = untracked.setdefault(name.lower(), {"name": name, "answers": 0, "questions": []})
            row["answers"] += 1
            if o.prompt_text not in row["questions"]:
                row["questions"].append(o.prompt_text)
    brands = sorted((b for b in untracked.values() if b["answers"] >= 2), key=lambda b: (-b["answers"], b["name"]))[:8]
    if brands:
        names = ", ".join(b["name"] for b in brands)
        found.append({
            "type": "UNTRACKED_COMPETITOR",
            "title": f"AI recommends {_plural(len(brands), 'brand')} you do not track",
            "description": f"AI recommended {names} in answers to your questions, but they are not on your competitor list.",
            "recommended_action": "Add them as competitors so your next scan shows where they beat you.",
            "impact": _impact(max(b["answers"] for b in brands) / total_answers if total_answers else 0),
            "confidence": _confidence(sum(b["answers"] for b in brands)),
            "evidence": {
                "brands": [{**b, "questions": b["questions"][:5]} for b in brands],
                "prompts": sorted({q for b in brands for q in b["questions"]})[:10],
            },
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

    _add_steps(found, observations, brand)
    for item in found:
        item["evidence"]["expected_objective"] = OBJECTIVES[item["type"]]
        item["evidence"]["effort"] = EFFORT[item["type"]]

    return sorted(found, key=lambda x: (IMPACT_ORDER[x["impact"]], -_weight(x["evidence"]), -x["confidence"]))


EFFORT = {"TECHNICAL_GAP": "S", "POSITIONING_GAP": "S", "UNTRACKED_COMPETITOR": "S", "ENTITY_GAP": "M", "CITATION_GAP": "M",
          "COMPARISON_GAP": "M", "COMPETITOR_GAP": "M", "CONTENT_GAP": "L"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _add_steps(found: list[dict], observations: list[Observation], brand: str) -> None:
    """Steps for the gaps that are not about specific lost questions (those got theirs from the questions)."""
    for item in found:
        ev, kind = item["evidence"], item["type"]
        if "steps" in ev:
            continue
        steps: list[str] = []
        if kind == "CITATION_GAP":
            for d in ev.get("domains", [])[:5]:
                steps.append(f"Get {brand} listed on {d['domain']}: ask for a review, submit a listing, or pitch the author ({d['citations']} citations).")
            steps.append("Start with the most cited source: find the exact page AI cited and ask to be added to it.")
            steps.append(f"Give each source the same one-line description of {brand} and a link to your homepage.")
            ev["why"] = [f"AI cited {d['domain']} {_plural(d['citations'], 'time')} in answers that recommended a competitor and left {brand} out."
                         for d in ev.get("domains", [])[:4]]
            ev["success_metric"] = f"At the next scan, at least one of these sources should cite an answer that names {brand}."
        elif kind == "POSITIONING_GAP":
            steps.append(f'Put one sentence at the top of your homepage: "{brand} is the best <category> for <audience> because <reason>."')
            steps.append("Add proof AI can quote: customer count, a named customer, and one measurable result.")
            steps.append("Use the same sentence on G2, Capterra, LinkedIn and Crunchbase.")
            ev["success_metric"] = f"At the next scan, AI should recommend {brand} in more than half of the answers that mention it."
        elif kind == "ENTITY_GAP":
            steps.append(f"Use one description of what {brand} is, word for word, in your homepage title, meta description and H1.")
            steps.append("Copy that description to LinkedIn, Crunchbase, G2 and Wikidata so AI links your name to the category.")
            ev["success_metric"] = f"At the next scan, AI should name {brand} in at least a third of answers to open category questions."
        elif kind == "UNTRACKED_COMPETITOR":
            steps.append(f"Add them as competitors: {', '.join(b['name'] for b in ev['brands'])}.")
            steps.append("Run a scan so you see which questions they win and why AI picks them.")
            ev["why"] = [f"AI recommended {b['name']} in {_plural(b['answers'], 'answer')}." for b in ev["brands"][:4]]
            ev["success_metric"] = "Every brand AI recommends for your questions is on your competitor list."
        elif kind == "TECHNICAL_GAP":
            steps.extend(f["action"] for f in ev.get("findings", []))
            ev["success_metric"] = "The next site audit reports none of these findings."
        ev["steps"] = steps


def status_summary(observations: list[Observation], brand: str, competitors: dict[int, str]) -> dict:
    """Where the project stands this scan, in one line, plus the 'alternatives to {brand}' answers kept out of the losses."""
    total = len(observations)
    rates = {name: sum(o.competitors.get(cid, {}).get("mentioned", False) for o in observations) for cid, name in competitors.items()}
    mine = sum(o.brand["mentioned"] for o in observations)
    rank = 1 + sum(n > mine for n in rates.values())
    lost = sum(_lost(o) for o in observations if not unwinnable(o, brand))
    pct = round(mine / total * 100) if total else 0
    to_win = f"{_plural(lost, 'answer')} to win back." if lost else "No answers lost to a competitor."
    if rank == 1:
        headline = f"You lead: AI names {brand} in {pct}% of answers. {to_win}"
    else:
        leader = max(rates, key=rates.get)
        headline = f"{leader} leads; you are #{rank}: AI names {brand} in {pct}% of answers. {to_win}"
    return {
        "headline": headline, "leading": rank == 1, "mention_rate": round(mine / total, 4) if total else 0.0, "rank": rank,
        "answers_lost": lost, "answers_total": total, "switching": switching(observations, brand, competitors),
    }


EFFORT_ORDER = {"S": 0, "M": 1, "L": 2}


def weekly_plan(rows: list[Opportunity]) -> list[Opportunity]:
    """This week's 3 actions: the biggest gaps first, quick wins before big projects. Done ones stay, to show progress."""
    live = [o for o in rows if o.trend != "resolved" and o.status != "dismissed"]
    return sorted(live, key=lambda o: (IMPACT_ORDER[o.impact], EFFORT_ORDER.get(o.evidence.get("effort"), 1), -o.confidence))[:3]


def fingerprint(item: dict) -> str:
    """Identity of a gap across scans: its type plus what it is about (a question category for question gaps)."""
    ev = item["evidence"]
    return f"{item['type']}:{ev.get('category') or ''}".lower()


def _weight(evidence: dict) -> int:
    """Size of a gap for trends: answers lost when it is about questions, otherwise how many items it lists."""
    if "answers_lost" in evidence:
        return evidence["answers_lost"]
    return len(evidence.get("prompts") or evidence.get("domains") or evidence.get("brands") or evidence.get("findings") or [])


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
