"""Opportunity engine (PRD sections 36-40): deterministic rules over stored
observations. Every opportunity carries the evidence that produced it."""

import re
from collections import Counter, defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.analysis.heuristic import name_pattern
from app.competitors.models import Competitor
from app.metrics.models import MetricSnapshot
from app.metrics.service import Observation, load_observations
from app.metrics.stats import significant
from app.opportunities.models import Opportunity
from app.prompts.models import Prompt
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
}
DISCOVERY_CATEGORIES = ("CATEGORY", "USE_CASE", "PROBLEM")
BRANDED_CATEGORIES = ("COMPARISON", "COMPETITOR", "ALTERNATIVE")
COMPARISON_CATEGORIES = ("COMPARISON", "COMPETITOR")
QUESTION_GAPS = ("CONTENT_GAP", "COMPETITOR_GAP", "COMPARISON_GAP")
SWITCH_CATEGORIES = ("ALTERNATIVE", "COMPETITOR")  # "alternatives to {brand}" cannot be won by naming the brand
HISTORY_SCANS = 2  # earlier full scans a question is judged over: with this one, the last 3
NEUTRAL_IMPORTANCE = 0.5  # a prompt with no importance set counts as average (the generator's default too)


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


def _key(o: Observation) -> tuple:
    """The same question across scans: scan prompts are per-scan copies, the prompt they came from is not."""
    return ("prompt", o.prompt_id) if o.prompt_id is not None else ("text", o.prompt_text.strip().lower())


def _by_question(observations: list[Observation]) -> dict[tuple, list[Observation]]:
    out: dict[tuple, list[Observation]] = defaultdict(list)
    for o in observations:
        out[_key(o)].append(o)
    return out


def _pages(observations: list[Observation], keep=lambda c: True) -> Counter:
    """How many of these answers cited each exact page."""
    return Counter((c["url"], c["domain"], c.get("source_type"), c.get("competitor_id"))
                   for o in observations for c in o.citations if keep(c))


def _top_pages(pages: Counter, n: int) -> list[dict]:
    return [{"url": u, "domain": d, "source_type": t, "competitor_id": cid, "count": k}
            for (u, d, t, cid), k in pages.most_common(n)]


def _question_rows(rows: list[Observation], competitors: dict[int, str], lost=_lost, history=(), importance=None) -> list[dict]:
    """One entry per question: how many engines it was lost on, and every competitor AI picked there, with its reason.
    `history` holds earlier scans' answers by question, so a loss can be checked against them; `importance` is each
    prompt's buyer value by prompt id, so the questions worth most come first."""
    by_question: dict[int, list[Observation]] = defaultdict(list)
    for o in rows:
        by_question[o.scan_prompt_id].append(o)
    out = []
    for answers in by_question.values():
        lost_answers = [o for o in answers if lost(o)]
        if not lost_answers:
            continue
        key = _key(answers[0])
        past = [scan[key] for scan in history if key in scan]
        winners: dict[int, dict] = {}
        domains: Counter = Counter()
        for o in lost_answers:
            domains.update(_third_party(o))
            for cid, v in o.competitors.items():
                if not v.get("recommended") or cid not in competitors:
                    continue
                w = winners.setdefault(cid, {"name": competitors[cid], "engines": 0, "reasons": Counter(), "quotes": {}, "quote": None})
                w["engines"] += 1
                reason, quote = (v.get("reason") or "").strip().rstrip("."), (v.get("evidence") or "").strip() or None
                if reason:
                    w["reasons"][reason] += 1
                    if quote:  # a reason is only ever shown with a quote from the same answer
                        w["quotes"].setdefault(reason, quote)
                w["quote"] = w["quote"] or quote
        value = (importance or {}).get(answers[0].prompt_id)
        out.append({
            "text": answers[0].prompt_text,
            "category": answers[0].category,
            "importance": NEUTRAL_IMPORTANCE if value is None else value,
            "response_ids": [o.response_id for o in lost_answers],
            "engines_lost": len(lost_answers),
            "engines_total": len(answers),
            "winners": [
                {"name": w["name"], "engines": w["engines"], "reason": reason,
                 "quote": w["quotes"].get(reason) if reason else w["quote"]}
                for w in sorted(winners.values(), key=lambda w: (-w["engines"], w["name"]))
                for reason in [w["reasons"].most_common(1)[0][0] if w["reasons"] else None]
            ],
            "cited_domains": [d for d, _ in domains.most_common(5)],
            # Every page AI read for these answers except your own, competitors' included: the steps depend on it.
            "cited_pages": _top_pages(_pages(lost_answers, lambda c: not c["is_brand_owned"]), 5),
            "scans_lost": 1 + sum(any(lost(o) for o in answers) for answers in past),
            "scans_seen": 1 + len(past),
        })
    return sorted(out, key=lambda q: (-q["importance"] * q["engines_lost"], -q["engines_lost"], q["text"]))


def _why(questions: list[dict], brand: str) -> list[str]:
    """2-4 sentences on why AI picked others, from the reasons it gave (most frequent first). The reason is the
    analysis model's paraphrase, so it is labelled a summary; only the verified quote from the answer is in quotes."""
    reasons: Counter = Counter()
    quotes: dict[tuple, str] = {}
    for q in questions:
        for w in q["winners"]:
            if w["reason"]:
                reasons[(w["name"], w["reason"])] += w["engines"]
                if w["quote"]:
                    quotes.setdefault((w["name"], w["reason"]), w["quote"])
    why = [
        f"AI picked {name} in {_plural(n, 'answer')} (summary: {reason})"
        + (f": \"{quotes[(name, reason)]}\"" if (name, reason) in quotes else ".")
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
        if winners:
            why.append(f"AI recommended {', '.join(n for n, _ in winners.most_common(3))} instead, without giving a reason.")
        else:
            why.append(f"AI answered without recommending {brand} or any competitor you track, and cited no sources.")
    return why[:4]


# Topics a founder can act on, spotted in the question or in the reasons AI gave for a competitor. Whole words only
# ("feedback" is not "fee"), and steps any industry can follow.
TOPICS = [
    (re.compile(r"\b(support|customer (service|care)|help ?desk|complaints?|grievances?)\b", re.I),
     "Publish a customer support page listing every channel (phone, chat, email, in-app), hours, and the response time you commit to."),
    (re.compile(r"\b(prices?|pricing|priced|fees?|charges?|costs?|cheap|cheaper|cheapest|affordable|afford)\b", re.I),
     "Publish a plain pricing page: every fee in one table, with a worked example of what a typical customer pays."),
    (re.compile(r"\b(beginners?|easy|easiest|simple|first[- ]time|new to|interface|user[- ]friendly)\b", re.I),
     "Publish a beginner's guide that walks a first-time user through sign-up to first use, with screenshots."),
    (re.compile(r"\b(documentation|documented|docs|guides?|tutorials?|learn|learning|education|educational|research|tools?)\b", re.I),
     "Publish learning resources (guides, tutorials, glossary) on your site and link them from your homepage."),
    (re.compile(r"\b(safe|safety|secure|security|trust|trusted|trustworthy|compliance|compliant|privacy|fraud)\b", re.I),
     "Publish a trust page: your security practices, certifications, data privacy policy and how you keep customer data safe."),
    (re.compile(r"\b(reviews?|ratings?|rated|reputation|popular|largest|users)\b", re.I),
     "Show proof AI can quote on your homepage: customer count, ratings with their source, and a named customer result."),
]


def _source_step(page: dict, brand: str, competitors: dict[int, str]) -> str:
    """What to do about one page AI cited, by the kind of site it is."""
    url, domain, kind = page["url"], page["domain"], page["source_type"]
    competitor = competitors.get(page.get("competitor_id"))
    if kind == "review_site":
        return f"Get {brand} reviewed on {domain}: AI cited {url}. Ask happy customers to leave a review there."
    if kind == "reddit":
        return f"Answer in the Reddit thread AI cited ({url}): say openly that you work on {brand} and who it is for."
    if kind == "news":
        return f"Pitch the author of the article AI cited ({url}) with a story or data about {brand}."
    if kind == "directory":
        return f"Submit a listing for {brand} on {domain}: AI cited {url}."
    if kind in ("comparison", "blog"):
        return f"Ask the author of {url} to add {brand} to that page: AI cited it in these answers."
    if kind == "competitor_website":
        rival = competitor or "that competitor"
        return f"Publish a page comparing {brand} with {rival}: AI used {rival}'s own page ({url}) in these answers."
    return f"Ask {domain} to mention {brand} on the page AI cited: {url}."


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
                steps.append(f"AI credits {w['name']} for this (summary: {w['reason']}): show, with specifics, how {brand} does it on the new page.")
    pages: Counter = Counter()
    for q in questions:
        for p in q.get("cited_pages", []):
            pages[(p["url"], p["domain"], p["source_type"], p["competitor_id"])] += p["count"]
    for page in _top_pages(pages, 3):
        competitor = competitors.get(page["competitor_id"])
        if competitor and any(f"-vs-{_slug(competitor)}:" in step for step in steps):
            continue  # the comparison page for that competitor is already a step
        steps.append(_source_step(page, brand, competitors))
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
    """A gap is confirmed once one of its questions was lost in 2 of the scans it was asked in; its confidence is
    the share of its (question, scan) pairs that were lost, so one unlucky run cannot read as certain."""
    lost = sum(q["engines_lost"] for q in questions)
    weighted = round(sum(q["importance"] * q["engines_lost"] for q in questions), 2)
    top = max(questions, key=lambda q: (q["scans_lost"], q["scans_lost"] / q["scans_seen"], q["engines_lost"] / q["engines_total"]))
    return {
        "type": kind, "title": title, "description": description, "recommended_action": action,
        "impact": _impact(lost / total_answers if total_answers else 0),
        "confidence": round(min(0.95, sum(q["scans_lost"] for q in questions) / sum(q["scans_seen"] for q in questions)), 2),
        "evidence": {
            "category": category, "prompts": [q["text"] for q in questions][:10], "questions": questions,
            "answers_lost": lost, "weighted_answers_lost": weighted, "confirmed": any(q["scans_lost"] >= 2 for q in questions),
            "consistency": (f"Lost in {top['scans_lost']} of {_plural(top['scans_seen'], 'scan')}, "
                            f"on {top['engines_lost']} of {_plural(top['engines_total'], 'engine')}"),
            "why": _why(questions, brand),
            "steps": _steps(kind, category, questions, brand, competitors),
            "success_metric": _success_metric(questions, brand, engines),
        },
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def switching(observations: list[Observation], brand: str, competitors: dict[int, str]) -> list[dict]:
    """'Alternatives to {brand}' answers: where your customers would switch. Evidence, never a loss."""
    rows = [o for o in observations if unwinnable(o, brand)]
    questions = _question_rows(rows, competitors, lost=lambda o: any(v.get("recommended") for v in o.competitors.values()))
    for q in questions:  # not a loss, so no "lost in N scans" line
        del q["scans_lost"], q["scans_seen"]
    return questions


def detect(
    observations: list[Observation], brand: str, competitors: dict[int, str], audit: dict | None = None,
    history: list[list[Observation]] | None = None, importance: dict[int, float | None] | None = None,
) -> list[dict]:
    """This scan's gaps. `history` is the answers of earlier full scans (newest first), to confirm lost questions;
    `importance` is each prompt's buyer value by prompt id (missing or None counts as average)."""
    found: list[dict] = []
    past = [_by_question(scan) for scan in history or []]
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
            questions = _question_rows(rows, competitors, lost=lambda o: not o.brand["mentioned"], history=past, importance=importance)
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
        questions = _question_rows(rows, competitors, history=past, importance=importance)
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
        lost_to_rivals = [o for o in winnable if not o.brand["mentioned"] and any(v.get("recommended") for v in o.competitors.values())]
        sources = {d for d, _ in missing}
        pages = _pages(lost_to_rivals, lambda c: c["domain"] in sources and not c["is_brand_owned"] and not c["competitor_id"])
        found.append({
            "type": "CITATION_GAP",
            "title": f"{_plural(len(missing), 'source')} AI cites for competitors never cite{'s' if len(missing) == 1 else ''} you",
            "description": "These sites are repeatedly cited in answers that recommend your competitors and never in answers that mention you.",
            "recommended_action": "Get listed, reviewed, or mentioned on these sources, starting with the most cited.",
            "impact": _impact(sum(n for _, n in missing) / total_answers if total_answers else 0),
            "confidence": _confidence(sum(n for _, n in missing)),
            "evidence": {
                "domains": [{"domain": d, "citations": n} for d, n in missing[:8]],
                "pages": [{k: p[k] for k in ("url", "domain", "source_type", "count")} for p in _top_pages(pages, 8)],
            },
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
    # Low-impact findings are tips (no llms.txt, training-only blocks): they ride along but never make a gap alone.
    if audit and any(f["impact"] != "low" for f in audit["findings"]):
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

    return sorted(found, key=lambda x: rank(x["impact"], x["evidence"], x["confidence"]))


def rank(impact: str, evidence: dict, confidence: float) -> tuple:
    """Order of gaps: biggest impact first, then confirmed before unconfirmed, then what the lost answers were worth
    to buyers (answers lost weighted by each question's importance), then confidence. Gaps not judged across scans
    (citations, site audit...) are not held back and are sized by how many items they list."""
    size = evidence["weighted_answers_lost"] if "weighted_answers_lost" in evidence else _weight(evidence)
    return (IMPACT_ORDER.get(impact, 9), not evidence.get("confirmed", True), -size, -confidence)


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
            steps.extend(_source_step(page, brand, {}) for page in ev.get("pages", [])[:5])  # most cited page first
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
    """This week's 3 actions: gaps seen this scan before ones that just went missing, the biggest first, confirmed
    before unconfirmed, quick wins before big projects. Done ones stay, to show progress."""
    live = [o for o in rows if o.trend != "resolved" and o.status != "dismissed"]
    return sorted(live, key=lambda o: (
        o.trend == "improving", IMPACT_ORDER[o.impact], not o.evidence.get("confirmed", True),
        EFFORT_ORDER.get(o.evidence.get("effort"), 1), -o.confidence, o.id,  # ties keep the order they were stored in
    ))[:3]


def fingerprint(item: dict) -> str:
    """Identity of a gap across scans: what it is about (its type, or for question gaps their category)."""
    ev = item["evidence"]
    # One identity per question category whatever the gap type, so a category moving between content,
    # competitor and comparison gaps stays the same opportunity instead of looking fixed.
    kind = "question_gap" if item["type"] in QUESTION_GAPS else item["type"]
    return f"{kind}:{ev.get('category') or ''}".lower()


def _weight(evidence: dict) -> int:
    """Size of a gap for trends: answers lost when it is about questions, otherwise how many items it lists."""
    if "answers_lost" in evidence:
        return evidence["answers_lost"]
    return len(evidence.get("prompts") or evidence.get("domains") or evidence.get("brands") or evidence.get("findings") or [])


def _answers(evidence: dict) -> int:
    return sum(q.get("engines_total", 0) for q in evidence.get("questions") or [])


def _change(old: Opportunity, item: dict) -> str:
    """better / worse only when the change is bigger than run-to-run noise. Question gaps compare the share of
    their answers that was lost; other gaps their impact and how many items they list."""
    if "answers_lost" in old.evidence and "answers_lost" in item["evidence"]:
        n_before, n_now = _answers(old.evidence), _answers(item["evidence"])
        before = old.evidence["answers_lost"] / n_before if n_before else None
        now = item["evidence"]["answers_lost"] / n_now if n_now else None
        if significant(before, n_before, now, n_now):
            return "worse" if now > before else "better"
        return "open"
    before, now = _weight(old.evidence), _weight(item["evidence"])
    worse = IMPACT_ORDER[item["impact"]] < IMPACT_ORDER[old.impact] or now > before
    better = IMPACT_ORDER[item["impact"]] > IMPACT_ORDER[old.impact] or now < before
    return "worse" if worse else "better" if better else "open"


def generate_and_store(
    session: Session, scan: Scan, brand: str, observations: list[Observation], audit: dict | None = None
) -> list[Opportunity]:
    """Stores this scan's opportunities, carrying each one's status and history from the previous scan.
    A gap missing once is stored as "improving"; missing two scans in a row, as "resolved", so the user sees what
    their work fixed and one lucky run does not close a gap."""
    competitors = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
    # Only full scans get a snapshot, so these are the earlier full scans, newest first.
    earlier = session.scalars(
        select(MetricSnapshot.scan_id).where(MetricSnapshot.project_id == scan.project_id, MetricSnapshot.scan_id < scan.id)
        .order_by(MetricSnapshot.scan_id.desc()).limit(HISTORY_SCANS)
    ).all()
    history = [load_observations(session, scan_id) for scan_id in earlier]
    # Scan prompts do not copy importance: read it from the prompts they came from.
    prompt_ids = {o.prompt_id for o in observations if o.prompt_id is not None}
    importance = dict(session.execute(select(Prompt.id, Prompt.importance).where(Prompt.id.in_(prompt_ids))).all()) if prompt_ids else {}
    session.execute(delete(Opportunity).where(Opportunity.scan_id == scan.id))
    previous_scan = session.scalar(
        select(func.max(Opportunity.scan_id)).where(Opportunity.project_id == scan.project_id, Opportunity.scan_id < scan.id)
    )
    previous = {
        o.fingerprint: o
        for o in session.scalars(select(Opportunity).where(Opportunity.scan_id == previous_scan, Opportunity.trend != "resolved"))
    } if previous_scan else {}
    # Question-gap fingerprints used to be "{type}:{category}". Rows stored that way cannot be matched to
    # today's "question_gap:{category}", so re-baseline instead of reporting them as fixed.
    previous = {fp: o for fp, o in previous.items() if fp.split(":", 1)[0].upper() not in QUESTION_GAPS}

    rows = []
    for item in detect(observations, brand, competitors, audit, history=history, importance=importance):
        fp = fingerprint(item)
        old = previous.pop(fp, None)
        row = Opportunity(project_id=scan.project_id, scan_id=scan.id, fingerprint=fp, **item)
        if old is None:
            row.trend, row.first_seen_scan_id = "new", scan.id
        else:
            before = _weight(old.evidence)
            row.trend = _change(old, item)
            row.status = "open" if old.status == "completed" else old.status  # marked done but still there: back on the list
            row.first_seen_scan_id = old.first_seen_scan_id or old.scan_id
            row.experiment_id = old.experiment_id
            row.evidence = {**item["evidence"], "previous_count": before,
                            **({"retest": old.evidence["retest"]} if "retest" in old.evidence else {})}
        rows.append(row)
    for fp, old in previous.items():  # gone this scan: improving; gone two scans in a row: fixed
        resolved = old.trend == "improving"
        rows.append(Opportunity(
            project_id=scan.project_id, scan_id=scan.id, fingerprint=fp, type=old.type, title=old.title,
            description=old.description, recommended_action=old.recommended_action, impact=old.impact,
            confidence=old.confidence, evidence=old.evidence, trend="resolved" if resolved else "improving",
            status=("dismissed" if old.status == "dismissed" else "completed") if resolved else old.status,
            first_seen_scan_id=old.first_seen_scan_id or old.scan_id, experiment_id=old.experiment_id,
        ))
    session.add_all(rows)
    session.flush()
    return rows
