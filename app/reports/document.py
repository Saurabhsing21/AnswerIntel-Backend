"""What the PDF says, page by page, worked out from a report's frozen content. Rules only, no AI calls: the
renderer in pdf-renderer/ only draws what this returns. Old reports lack some keys, so every read has a default."""

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

YOU = "#C8373F"
PALETTE = ("#12A37F", "#3B6FD8", "#8B5CF6", "#E07A2E", "#D9488B", "#14A3A3")
OPEN = "#C98A1B"

# Buying stage of each question category, in the order a buyer meets them.
STAGES = (
    ("PROBLEM", "Problem", "Describes a pain, not a product"),
    ("DISCOVERY", "Discovery", "Asks for a list of options"),
    ("USE_CASE", "Use case", "Needs one specific job done"),
    ("ALTERNATIVE", "Alternatives", "Wants something other than a known brand"),
    ("COMPARISON", "Comparison", "Compares brands by name"),
)
STAGE_OF = {
    "PROBLEM": "PROBLEM", "CATEGORY": "DISCOVERY", "BUYER_INTENT": "DISCOVERY", "USE_CASE": "USE_CASE",
    "ALTERNATIVE": "ALTERNATIVE", "COMPARISON": "COMPARISON", "COMPETITOR": "COMPARISON",
}
STAGE_COLORS = {"PROBLEM": "#D9488B", "DISCOVERY": "#2E9BD6", "USE_CASE": "#14A3A3", "ALTERNATIVE": "#8B5CF6", "COMPARISON": "#E07A2E"}
WHY_FITS = {
    "PROBLEM": "Pain-led; a clear guide can own it",
    "DISCOVERY": "High intent; the buyer is ready to pick",
    "USE_CASE": "One specific job a single page can answer",
    "ALTERNATIVE": "The buyer is ready to switch",
    "COMPARISON": "The buyer is choosing between named brands",
}
PRIORITY = {"PROBLEM": "MEDIUM", "DISCOVERY": "HIGH", "USE_CASE": "HIGH", "ALTERNATIVE": "HIGH", "COMPARISON": "MEDIUM"}
WEB_ENGINES = {"ChatGPT Search", "Perplexity", "Gemini", "Google AI Mode"}
SUGGESTED_ENGINES = ("ChatGPT Search", "Perplexity", "Gemini", "Google AI Mode")
ZONES = {"IN": "Asia/Kolkata", "US": "America/New_York", "GB": "Europe/London", "AU": "Australia/Sydney", "SG": "Asia/Singapore", "AE": "Asia/Dubai"}
QUESTIONS_PER_PAGE = 32
MAX_GRID_BRANDS = 4
MAX_OPEN_ROWS = 12


def pct(rate: float | None) -> str:
    return "–" if rate is None else f"{round(rate * 100)}%"


def wilson(rate: float, n: int) -> tuple[float, float]:
    """95% range of a rate measured on n answers (Wilson score interval)."""
    if not n:
        return 0.0, 0.0
    z = 1.96
    centre = (rate + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def span(rate: float, n: int) -> str:
    lo, hi = wilson(rate, n)
    return f"{round(lo * 100)}–{round(hi * 100)}%"


def score(mention: float, recommend: float, cite: float) -> int:
    return round(100 * (0.4 * mention + 0.4 * recommend + 0.2 * cite))


def score_label(value: int) -> str:
    return "NOT VISIBLE" if value < 10 else "EMERGING" if value < 30 else "VISIBLE" if value < 60 else "LEADING"


def _local(iso: str | None, country: str | None) -> datetime:
    when = datetime.fromisoformat(iso) if iso else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(ZoneInfo(ZONES.get((country or "").upper(), "UTC")))


def _slug(name: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in name).split())


def _q_range(numbers: list[int]) -> str:
    if not numbers:
        return "–"
    if numbers == list(range(numbers[0], numbers[-1] + 1)) and len(numbers) > 2:
        return f"Q{numbers[0]}–Q{numbers[-1]}"
    return ", ".join(f"Q{n}" for n in numbers[:4]) + (" …" if len(numbers) > 4 else "")


def build_document(content: dict, report_id: int | None = None) -> dict:
    brand = content["brand"]
    meta = content.get("meta") or {}
    vis = content["visibility"]
    n = vis.get("total_responses") or meta.get("answers") or 0
    country = meta.get("country")
    scan_no = max(1, meta.get("scans_in_trend") or 1)
    engines_used = meta.get("engines") or [e["name"] for e in content.get("engines", [])]

    # Rivals ordered by how often AI names them; the most named is the leader.
    rivals = sorted((c for c in content.get("competitors", []) if not c["is_you"]), key=lambda c: -c["mention_rate"])
    colors = {c["name"]: PALETTE[i % len(PALETTE)] for i, c in enumerate(rivals)} | {brand: YOU}
    leader = rivals[0] if rivals else None

    rows = []
    for q in content.get("questions") or []:
        picked = q.get("picked") or q.get("winners") or []
        you = "PICKED" if q.get("recommended_on") else "NAMED" if q.get("seen_on") else "MISSING"
        stage = STAGE_OF.get(q.get("category") or "", "DISCOVERY")
        rows.append({"text": q["text"], "stage": stage, "you": you, "picked": picked, "open": you != "PICKED" and not picked})
    # Questions with a pick first, open ones last.
    rows.sort(key=lambda r: (r["open"], r["you"] != "PICKED", -len(r["picked"])))
    for i, r in enumerate(rows, 1):
        r["n"] = i
    total_q = len(rows)
    open_rows = [r for r in rows if r["open"]]
    open_n = len(open_rows)

    def wins(name: str) -> int:
        return sum(r["you"] == "PICKED" for r in rows) if name == brand else sum(name in r["picked"] for r in rows)

    cite_n = max(n, 1)
    brands = [{
        "name": brand, "is_you": True, "color": YOU,
        "mention": vis["mention_rate"], "recommend": vis["recommendation_rate"], "range": span(vis["recommendation_rate"], n),
        "avg_rank": vis.get("average_position"), "sov": vis.get("share_of_voice") or 0,
        "score": score(vis["mention_rate"], vis["recommendation_rate"], vis.get("citation_rate") or 0), "wins": wins(brand),
    }] + [{
        "name": c["name"], "is_you": False, "color": colors[c["name"]],
        "mention": c["mention_rate"], "recommend": c["recommendation_rate"], "range": span(c["recommendation_rate"], n),
        "avg_rank": c.get("average_position"), "sov": c.get("share_of_voice") or 0,
        "score": score(c["mention_rate"], c["recommendation_rate"], min(1.0, (c.get("citation_count") or 0) / cite_n)),
        "wins": wins(c["name"]),
    } for c in rivals]
    you_row = brands[0]
    leader_row = brands[1] if leader else None
    ranked_rivals = sorted((b for b in brands if not b["is_you"] and b["wins"]), key=lambda b: -b["wins"])

    # Buying stages: each question counted once, under the first brand AI picked (or "Open").
    stages = []
    for key, label, desc in STAGES:
        mine = [r for r in rows if r["stage"] == key]
        if not mine:
            continue
        segments: dict[str, int] = {}
        for r in mine:
            winner = brand if r["you"] == "PICKED" else (r["picked"][0] if r["picked"] else "Open")
            segments[winner] = segments.get(winner, 0) + 1
        stages.append({
            "key": key, "label": label, "desc": desc, "color": STAGE_COLORS[key], "count": len(mine),
            "open": sum(r["open"] for r in mine), "you": sum(r["you"] == "PICKED" for r in mine),
            "segments": [{"name": k, "count": v, "color": OPEN if k == "Open" else colors.get(k, "#94A3B8")}
                         for k, v in sorted(segments.items(), key=lambda kv: (kv[0] == "Open", -kv[1]))],
            "wins": {b["name"]: sum(b["name"] in r["picked"] for r in mine) for b in brands if not b["is_you"]},
        })

    cited = content.get("engine_citations") or {}
    engine_rows = [{
        "name": e["name"], "type": "Live web search" if e["name"] in WEB_ENGINES else "Model memory (no live web)",
        "answers": e["responses"], "mention": pct(e["mention_rate"]), "recommend": pct(e["recommendation_rate"]),
        "cited": pct(cited[e["name"]]) if e["name"] in cited else "–", "scanned": True,
    } for e in content.get("engines", [])]
    missing_engines = [e for e in SUGGESTED_ENGINES if e not in engines_used]
    engine_rows += [{"name": e, "type": "Live web search", "scanned": False} for e in missing_engines]

    sources = content.get("sources") or []
    reasons = content.get("competitor_reasons") or {}
    competitor_why = []
    for b in ranked_rivals[:3]:
        r = reasons.get(b["name"]) or {}
        strong = [s["label"].lower() for s in sorted(stages, key=lambda s: -s["wins"].get(b["name"], 0))[:2] if s["wins"].get(b["name"])]
        items = [{"title": x["text"], "detail": f"Given in {x['count']} answer{'s' if x['count'] != 1 else ''}", "stated": True}
                 for x in r.get("reasons", [])[:3]]
        if not items:
            items = [{"title": f"Picked on {b['wins']} of {total_q} questions",
                      "detail": f"Mostly {' and '.join(strong)} questions" if strong else "Across the question set", "stated": False}]
        competitor_why.append({"name": b["name"], "color": b["color"], "wins": b["wins"], "items": items, "quote": r.get("quote")})

    claims = [{"claim": i["title"], "competitor": c["name"]} for c in competitor_why for i in c["items"] if i["stated"]][:5]
    for i, c in enumerate(claims):
        c["page"] = "Homepage hero and FAQ" if i == 0 else "Dedicated feature page"

    # Action plan: ranked rules, each tied to the questions it targets. start and length are in weeks (1-12).
    category = content.get("category") or "your category"
    actions = []
    if open_rows:
        actions.append({"title": f"Answer the {open_n} open question{'s' if open_n != 1 else ''}",
                        "detail": "One page or FAQ entry per question in Section 04, with a short, direct answer in the first paragraph.",
                        "targets": _q_range([r["n"] for r in open_rows]), "impact": "High", "effort": "Low", "when": "Weeks 1–2", "start": 1, "length": 2})
    if ranked_rivals:
        top = ranked_rivals[0]
        actions.append({"title": f"Publish /{_slug(brand)}-vs-{_slug(top['name'])}",
                        "detail": "Honest feature and pricing table. Open with a one-sentence verdict on who each option suits.",
                        "targets": f"{top['wins']} {top['name']} wins", "impact": "High", "effort": "Low", "when": "Weeks 1–2", "start": 1, "length": 2})
    if len(ranked_rivals) > 1:
        others = ranked_rivals[1:3]
        pages = " and ".join(f"/{_slug(brand)}-vs-{_slug(b['name'])}" for b in others)
        actions.append({"title": f"Publish {pages}", "detail": "Same format. Targets buyers already comparing or looking to switch.",
                        "targets": " + ".join(f"{b['wins']} {b['name']}" for b in others) + " wins", "impact": "High", "effort": "Low", "when": "Weeks 2–4", "start": 2, "length": 3})
    actions.append({"title": "Fix the brand description everywhere",
                    "detail": "The same one-line description on the homepage, app stores, social bios and press kit.",
                    "targets": "All", "impact": "Medium", "effort": "Low", "when": "Week 1", "start": 1, "length": 1})
    discovery = next((s for s in stages if s["key"] == "DISCOVERY"), None)
    actions.append({"title": "Category guide pages",
                    "detail": f"\"Best {category} in {country or 'your market'}\" and buyer guides for the questions AI answers with a list.",
                    "targets": f"Discovery ({discovery['count']})" if discovery else "All", "impact": "High", "effort": "Medium",
                    "when": "Month 1–2", "start": 4, "length": 5})
    trusted = [s["domain"] for s in sources if not s.get("with_you")][:3]
    actions.append({"title": "Earn third-party mentions",
                    "detail": (f"Get listed or reviewed on {', '.join(trusted)}: AI cites them for your competitors." if trusted
                               else "Round-up articles, creator videos and community threads (Section 07)."),
                    "targets": "All", "impact": "High", "effort": "High", "when": "Month 1–3", "start": 4, "length": 9})
    actions.append({"title": "Add structured data", "detail": "FAQ and Organization schema; link the new pages from the homepage.",
                    "targets": "All", "impact": "Medium", "effort": "Low", "when": "Week 2", "start": 2, "length": 1})
    actions = actions[:7]

    mention, recommend, cite = vis["mention_rate"], vis["recommendation_rate"], vis.get("citation_rate") or 0
    sentiment = vis.get("positive_sentiment_rate")
    site = (content.get("website") or "").removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")

    def goal(today: float, first: str, step30: float, lo90: float, hi90: float) -> dict:
        if today < lo90:
            d90, end = f"{round(lo90 * 100)}–{round(hi90 * 100)}%", hi90
        else:
            end = min(1.0, today + hi90)
            d90 = f"{pct(min(1, today + lo90))}–{pct(end)}"
        return {"today": pct(today), "d30": first if today == 0 else pct(min(1, today + step30)), "d90": d90,
                "values": [today, min(1, today + step30), end]}

    open_goal = [{"metric": "Open questions won", "today": f"0 of {open_n}", "d30": f"1–2 of {open_n}",
                  "d90": f"{math.ceil(open_n / 2)}+ of {open_n}", "values": [0, min(1, 2 / open_n), 0.5], "where": "Section 04 questions"}] if open_n else []
    goals = [
        {"metric": "Mention rate", **goal(mention, "First mentions", 0.05, 0.10, 0.15), "where": "Web-search engines"},
        {"metric": "Recommendation rate", **goal(recommend, "1–2 questions", 0.03, 0.05, 0.10), "where": "Open questions (Section 04)"},
        *open_goal,
        {"metric": "Citation rate", **goal(cite, f"{site or 'Your site'} cited once", 0.03, 0.05, 0.10), "where": "Perplexity, ChatGPT Search"},
        {"metric": "Sentiment when mentioned", "today": pct(sentiment) if mention and sentiment is not None else "n/a",
         "d30": "Neutral or better", "d90": "Mostly positive", "values": None, "where": "All engines"},
    ]

    next_setup = []
    if missing_engines:
        next_setup.append({"big": str(len(engines_used) + len(missing_engines)), "title": "More engines", "detail": ", ".join(missing_engines)})
    if open_n:
        next_setup.append({"big": str(open_n), "title": "Open questions to re-check", "detail": "Re-run them after the new pages are live"})
    next_setup.append({"big": "1", "title": "Brand accuracy check", "detail": f"Ask \"What is {brand}?\" to catch wrong facts"})
    next_setup.append({"big": "7", "title": "Days between scans", "detail": "Trends become reliable after 3–4 scans"})

    # Executive summary: three findings, each from one number.
    findings = []
    if leader and leader["recommendation_rate"] > recommend:
        rank = f" (average rank {leader['average_position']:.1f})" if leader.get("average_position") else ""
        strong = [s["label"].lower() for s in sorted(stages, key=lambda s: -s["wins"].get(leader["name"], 0))[:2] if s["wins"].get(leader["name"])]
        findings.append({"lead": f"{leader['name']} is the default answer.",
                         "body": f"It is picked in {pct(leader['recommendation_rate'])} of answers{rank}"
                                 + (f", strongest on {' and '.join(strong)} questions." if strong else ".")})
    if open_n:
        most_open = max(stages, key=lambda s: s["open"])
        findings.append({"lead": "Part of the market is unclaimed.",
                         "body": f"{open_n} of {total_q} questions got no recommended brand, most of them {most_open['label'].lower()} questions."})
    if you_row["wins"]:
        best = max(stages, key=lambda s: s["you"])
        findings.append({"lead": f"{brand} already wins {you_row['wins']} question{'s' if you_row['wins'] != 1 else ''}.",
                         "body": f"Most of them at the {best['label'].lower()} stage. Protect these pages."})
    elif len(ranked_rivals) > 1:
        last = ranked_rivals[-1]
        findings.append({"lead": f"{last['name']} is rarely picked.",
                         "body": f"It wins {last['wins']} of {total_q} questions, so its buyers are open to a better answer."})
    if len(findings) < 3 and not sources:
        findings.append({"lead": "No websites were cited.", "body": "AI answered from memory, so being written about on trusted sites is the long-term lever."})

    if mention == 0:
        headline = f"{brand} is not yet visible in AI answers."
    elif leader and leader["mention_rate"] > mention:
        headline = f"{brand} is visible, but {leader['name']} is named more often."
    else:
        headline = f"{brand} leads the brands AI names for {category}."
    summary = [
        {"lead": headline, "body": f"Across {total_q} buyer questions put to {', '.join(engines_used)}, {brand} was named in {pct(mention)} of "
                                   f"{n} answers and recommended in {pct(recommend)}."
                                   + (f" {leader['name']} was recommended in {pct(leader['recommendation_rate'])}." if leader else "")},
        {"lead": "The market is not fully claimed." if open_n else "Every question has a favourite.",
         "body": f"In {open_n} of {total_q} questions ({pct(open_n / total_q)}) AI recommended no brand at all." if open_n
                 else "AI picked a brand on every question, so winning means displacing a competitor."},
        {"lead": f"{len(sources)} websites shaped the answers." if sources else "No websites were cited.",
         "body": f"The most cited was {sources[0]['domain']} ({sources[0]['citations']} citations). Section 07 lists where to be present."
                 if sources else "AI answered from what it learned in training. Being written about on trusted sites is the long-term lever."},
    ]

    deltas = vis.get("deltas") or {}
    metrics = [
        {"name": "Mention rate", "you": pct(mention), "range": span(mention, n), "delta": deltas.get("mention_rate"),
         "leader": f"{leader['name']} {pct(leader['mention_rate'])}" if leader else "–", "measures": f"Answers that name {brand}"},
        {"name": "Recommendation rate", "you": pct(recommend), "range": span(recommend, n), "delta": deltas.get("recommendation_rate"),
         "leader": f"{leader['name']} {pct(leader['recommendation_rate'])}" if leader else "–", "measures": f"Answers that suggest {brand} as a pick"},
        {"name": "Share of voice", "you": pct(you_row["sov"]), "range": "–", "delta": deltas.get("share_of_voice"),
         "leader": f"{leader['name']} {pct(leader.get('share_of_voice'))}" if leader else "–", "measures": f"{brand}'s slice of all brand picks"},
        {"name": "Citation rate", "you": pct(cite), "range": span(cite, n), "delta": deltas.get("citation_rate"),
         "leader": "–", "measures": f"Answers that link to {site or 'your site'}"},
        {"name": "Average rank", "you": f"#{vis['average_position']:.1f}" if vis.get("average_position") else "–", "range": "–", "delta": None,
         "leader": f"{leader['name']} #{leader['average_position']:.1f}" if leader and leader.get("average_position") else "–",
         "measures": "Position when listed among several brands"},
        {"name": "Sentiment", "you": f"{pct(sentiment)} positive" if mention and sentiment is not None else "n/a", "range": "–", "delta": None,
         "leader": "–", "measures": f"Tone used when {brand} is mentioned"},
    ]

    q_pages = max(1, math.ceil(total_q / QUESTIONS_PER_PAGE))
    sections = [
        ("Executive summary", "Your score, three key findings and the first thing to do", 1),
        ("Where you stand", "Every metric with its 95% range and gap to the leader", 1),
        ("Who AI recommends instead", "Competitor mentions, picks, share of voice and wins", 1),
        ("Results by buying stage", "Where buyers are in their journey and who wins each stage", 1),
        ("Open opportunities", f"The {open_n} question{'s' if open_n != 1 else ''} where AI recommended no brand", 1),
        ("Question-by-question results", f"All {total_q} questions with the brands AI picked", q_pages),
        ("Why AI picks your competitors", f"The reasons AI gives, and what {brand} must match", 1),
        ("Sources AI trusts", "Which sites AI cites, and where to be present", 1),
        ("Action plan", f"{len(actions)} ranked actions, impact vs effort, and a 90-day roadmap", 1),
        ("Goals for the next scan", "Targets to track progress and a better scan setup", 1),
        ("Methodology and glossary", "How the numbers were produced, plus key terms", 1),
    ]
    toc, page = [], 3
    for i, (title, desc, pages) in enumerate(sections):
        toc.append({"n": f"{i:02d}", "title": title, "desc": desc, "page": page})
        page += pages

    started = _local(meta.get("scan_started_at") or meta.get("generated_at"), country)
    generated = _local(meta.get("generated_at"), country)
    return {
        "brand": brand, "website": site, "category": category, "country": country or "–",
        "scan_no": scan_no, "baseline": scan_no == 1,
        "scan_date": f"{started:%d %b %Y}", "generated": f"{generated:%d %b %Y, %H:%M} {generated.tzname()}",
        "engines": engines_used, "questions": total_q, "answers": n,
        "answers_expected": total_q * max(1, len(engines_used)), "competitors": len(rivals),
        "you": you_row, "leader": leader_row, "brands": brands, "by_score": sorted(brands, key=lambda b: -b["score"]),
        "open_count": open_n, "score": you_row["score"], "score_label": score_label(you_row["score"]),
        "summary": summary, "findings": findings[:3], "do_first": actions[0] if actions else None,
        "metrics": metrics,
        "gaps": [
            {"name": "Mention rate", "you": mention, "leader": leader["mention_rate"] if leader else 0},
            {"name": "Recommendation rate", "you": recommend, "leader": leader["recommendation_rate"] if leader else 0},
            {"name": "Share of voice", "you": you_row["sov"], "leader": (leader.get("share_of_voice") or 0) if leader else 0},
        ],
        "engine_rows": engine_rows, "web_scanned": any(e in WEB_ENGINES for e in engines_used),
        "stages": stages,
        "open_rows": [{**r, "why": WHY_FITS[r["stage"]], "priority": PRIORITY[r["stage"]]} for r in open_rows[:MAX_OPEN_ROWS]],
        "open_more": max(0, open_n - MAX_OPEN_ROWS),
        "question_rows": rows, "questions_per_page": QUESTIONS_PER_PAGE,
        "grid_brands": [b for b in brands if not b["is_you"]][:MAX_GRID_BRANDS],
        "stage_labels": {k: label for k, label, _ in STAGES},
        "competitor_why": competitor_why, "claims": claims, "sources": sources[:8],
        "actions": actions, "goals": goals, "next_setup": next_setup[:5], "toc": toc,
    }
