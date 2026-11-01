"""Action plan engine on Groww-like data: the brand leads, loses 3 questions, one of them "alternatives to Groww"."""

from app.analysis import llm as llm_module
from app.analysis.base import AnalysisContext
from app.analysis.llm import AnalysisOutput, BrandVerdict
from app.analysis.service import ResponseAnalysisService
from app.metrics.service import Observation
from app.opportunities import site_audit
from app.opportunities import service
from app.opportunities.service import _why, detect, fingerprint, status_summary
from tests.conftest import API, make_project, signup

ENGINES = ("chatgpt", "gemini", "perplexity")
COMPETITORS = {1: "Zerodha", 2: "Upstox", 3: "Dhan", 4: "Angel One"}
SUPPORT_Q = "Which investing app has the best customer support while placing orders?"
BEGINNER_Q = "What is the best investing app for beginners in India?"
ALTERNATIVES_Q = "What are the best alternatives to Groww for stock trading in India?"


def rec(reason=None, quote=None, recommended=True):
    return {"mentioned": True, "recommended": recommended, "position": None, "sentiment": "positive", "reason": reason, "evidence": quote}


def answer(n, engine, q, text, category, groww, comps=None, domains=(), others=()):
    return Observation(
        response_id=n, engine=engine, scan_prompt_id=q, prompt_id=q, prompt_text=text, category=category,
        brand={"mentioned": groww, "recommended": groww, "position": 1 if groww else None, "sentiment": "positive" if groww else None},
        competitors=comps or {},
        citations=[{"url": f"https://{d}/x", "domain": d, "source_type": "other", "is_brand_owned": False, "competitor_id": None} for d in domains],
        other_brands=list(others),
    )


def groww_scan() -> list[Observation]:
    rows, n = [], 0

    def add(q, text, category, lost_on, comps=None, domains=(), others=()):
        nonlocal n
        for engine in ENGINES:
            n += 1
            lost = engine in lost_on
            rows.append(answer(n, engine, q, text, category, not lost, comps if lost else {},
                               domains if lost else (), others if lost else ()))

    support = {1: rec("highlighted for documentation", "Zerodha's support portal is well documented."),
               2: rec("beginner-friendly with simple interface and good support", "Upstox offers good support.")}
    add(1, SUPPORT_Q, "USE_CASE", ("chatgpt", "gemini"), support, ("moneycontrol.com",), ("ICICI Direct",))
    beginner = {2: rec("beginner-friendly with simple interface and good support"), 3: rec("low brokerage")}
    add(2, BEGINNER_Q, "CATEGORY", ("gemini", "perplexity"), beginner, ("moneycontrol.com",), ("ICICI Direct", "HDFC Securities"))
    alternatives = {1: rec("largest broker"), 2: rec("beginner-friendly"), 4: rec("full-service broker")}
    add(3, ALTERNATIVES_Q, "ALTERNATIVE", ENGINES, alternatives, (), ("HDFC Securities", "Kotak Securities"))
    for q, category in ((4, "CATEGORY"), (5, "CATEGORY"), (6, "USE_CASE"), (7, "BUYER_INTENT"), (8, "COMPARISON")):
        add(q, f"Groww question {q}", category, ())
    return rows


def found_by_type(rows=None):
    out: dict[str, list[dict]] = {}
    for item in detect(rows or groww_scan(), "Groww", COMPETITORS):
        out.setdefault(item["type"], []).append(item)
    return out


def test_alternatives_to_the_brand_is_never_a_loss_but_is_kept_as_switching_evidence():
    found = found_by_type()
    every_question = [q["text"] for items in found.values() for o in items for q in o["evidence"].get("questions", [])]
    assert ALTERNATIVES_Q not in every_question
    assert all(ALTERNATIVES_Q not in o["evidence"].get("prompts", []) for items in found.values() for o in items if o["type"] != "UNTRACKED_COMPETITOR")
    switch = status_summary(groww_scan(), "Groww", COMPETITORS)["switching"]
    assert [q["text"] for q in switch] == [ALTERNATIVES_Q]
    assert {w["name"] for w in switch[0]["winners"]} == {"Zerodha", "Upstox", "Angel One"}


def test_losses_are_grouped_by_question_type_with_every_winner_listed():
    gaps = found_by_type()["COMPETITOR_GAP"]
    # Two question types lost (use-case, category): two opportunities, not one per competitor.
    assert sorted(g["evidence"]["category"] for g in gaps) == ["CATEGORY", "USE_CASE"]
    texts = [q["text"] for g in gaps for q in g["evidence"]["questions"]]
    assert sorted(texts) == sorted([SUPPORT_Q, BEGINNER_Q]) and len(texts) == len(set(texts))
    support = next(q for g in gaps for q in g["evidence"]["questions"] if q["text"] == SUPPORT_Q)
    assert support["engines_lost"] == 2 and support["engines_total"] == 3 and support["category"] == "USE_CASE"
    assert support["cited_domains"] == ["moneycontrol.com"]
    assert support["winners"] == [
        {"name": "Upstox", "engines": 2, "reason": "beginner-friendly with simple interface and good support", "quote": "Upstox offers good support."},
        {"name": "Zerodha", "engines": 2, "reason": "highlighted for documentation", "quote": "Zerodha's support portal is well documented."},
    ]
    # Same grouping key across scans, so trends still work.
    assert {fingerprint(g) for g in gaps} == {"question_gap:category", "question_gap:use_case"}


def test_every_question_gap_explains_why_and_has_tailored_steps_and_a_success_metric():
    for gap in found_by_type()["COMPETITOR_GAP"]:
        ev = gap["evidence"]
        assert 2 <= len(ev["why"]) <= 4 and 5 <= len(ev["steps"]) <= 8
        assert ev["success_metric"].startswith("Re-test this question") and "at least 2 of 3 engines" in ev["success_metric"]
        assert ev["effort"] == "M" and ev["expected_objective"]
        assert not any("first paragraph of that page" in s or "-vs-" in s for s in ev["steps"])  # no unrelated pages
        for text in (gap["title"], gap["description"], gap["recommended_action"]):
            assert "prompt" not in text.lower()
    support = next(g for g in found_by_type()["COMPETITOR_GAP"] if g["evidence"]["category"] == "USE_CASE")
    steps = " ".join(support["evidence"]["steps"])
    assert "customer support page" in steps and "hours" in steps and "moneycontrol.com" in steps
    assert "documentation" in steps or "learning resources" in steps
    # The most frequent stated reason comes first.
    assert "Upstox: \"beginner-friendly with simple interface and good support\"" in support["evidence"]["why"][0]


def test_impact_is_scaled_by_share_of_answers_lost_not_raw_count():
    # 2 of 24 answers lost per question type: a leader's small gap is medium, not high.
    assert {g["impact"] for g in found_by_type()["COMPETITOR_GAP"]} == {"medium"}
    # The same two lost answers in a scan of 6 answers is a third of everything: high.
    small = [o for o in groww_scan() if o.scan_prompt_id in (1, 4)]
    gap = found_by_type(small)["COMPETITOR_GAP"][0]
    assert gap["impact"] == "high"


def test_comparison_losses_get_vs_pages_for_the_competitor_who_won_them():
    rows = [answer(i, e, 9, "Groww vs Zerodha for long-term investing?", "COMPARISON", False,
                   {1: rec("lower costs")}) for i, e in enumerate(ENGINES)]
    rows += [answer(10 + i, e, 10, "Groww question 10", "CATEGORY", True) for i, e in enumerate(ENGINES)]
    gap = found_by_type(rows)["COMPARISON_GAP"][0]
    assert gap["title"] == "You lose 1 comparison question to Zerodha"
    assert any(s.startswith("Publish /groww-vs-zerodha") and "long-term investing" in s for s in gap["evidence"]["steps"])
    assert "COMPETITOR_GAP" not in found_by_type(rows)


def test_status_block_says_who_leads_and_what_is_left_to_win():
    status = status_summary(groww_scan(), "Groww", COMPETITORS)
    assert {k: status[k] for k in ("leading", "rank", "answers_lost", "answers_total")} == {
        "leading": True, "rank": 1, "answers_lost": 4, "answers_total": 24,
    }
    assert status["mention_rate"] == round(17 / 24, 4)
    assert status["headline"] == "You lead: AI names Groww in 71% of answers. 4 answers to win back."
    behind = status_summary([o for o in groww_scan() if o.scan_prompt_id == 3], "Groww", COMPETITORS)
    assert behind["leading"] is False and behind["rank"] == 4
    assert behind["headline"] == "Zerodha leads; you are #4: AI names Groww in 0% of answers. No answers lost to a competitor."


def test_untracked_brands_ai_recommended_become_one_opportunity():
    gap = found_by_type()["UNTRACKED_COMPETITOR"][0]
    assert [(b["name"], b["answers"]) for b in gap["evidence"]["brands"]] == [
        ("HDFC Securities", 5), ("ICICI Direct", 4), ("Kotak Securities", 3),
    ]
    assert gap["evidence"]["steps"][0] == "Add them as competitors: HDFC Securities, ICICI Direct, Kotak Securities."
    # A brand recommended once is too thin to act on.
    once = [o for o in groww_scan() if o.scan_prompt_id != 3]
    once[0].other_brands = ["Paytm Money"]
    assert "Paytm Money" not in found_by_type(once)["UNTRACKED_COMPETITOR"][0]["description"]
    assert gap["evidence"]["brands"][1]["questions"] == [SUPPORT_Q, BEGINNER_Q]


def test_analysis_captures_recommended_brands_that_are_not_tracked(monkeypatch):
    monkeypatch.setattr(llm_module, "complete_json", lambda *a, **k: AnalysisOutput(
        brands=[BrandVerdict(name="Groww", mentioned=False, recommended=False),
                BrandVerdict(name="Zerodha", mentioned=True, recommended=True)],
        other_brands=["ICICI Direct", "zerodha", "Made Up Broker", "ICICI Direct"],
    ))
    ctx = AnalysisContext(brand_name="Groww", competitors=[{"id": 1, "name": "Zerodha"}], prompt="best broker")
    result = ResponseAnalysisService(use_llm=True).analyze("Try Zerodha or ICICI Direct.", ctx)
    # Tracked names, duplicates and names absent from the answer are dropped.
    assert result["other_brands"] == ["ICICI Direct"]


def test_structured_data_found_past_the_old_200kb_limit_and_not_reported_on_a_cut_off_page():
    late = "<html><body>" + "<p>Invest in stocks. </p>" * 11_000 + "<script type='application/ld+json'>{}</script></body></html>"
    assert len(late) > 200_085

    def site(html):
        return lambda url: (200, "User-agent: *\nAllow: /") if url.endswith("robots.txt") else (200, "# Groww") if url.endswith("llms.txt") else (200, html)

    assert site_audit.audit_site("https://groww.in", fetch=site(late))["findings"] == []
    cut_off = "<html><body>" + "x" * site_audit.MAX_PAGE_BYTES  # read limit hit: JSON-LD could be further down
    assert "NO_STRUCTURED_DATA" not in {f["code"] for f in site_audit.audit_site("https://groww.in", fetch=site(cut_off))["findings"]}


def test_list_can_include_the_status_block(client):
    headers = signup(client, "statusblock")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    plain = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    body = client.get(f"{API}/projects/{project_id}/opportunities?with_status=true", headers=headers).json()
    assert isinstance(plain, list) and [o["id"] for o in body["items"]] == [o["id"] for o in plain]
    status = body["status"]
    assert set(status) == {"headline", "leading", "mention_rate", "rank", "answers_lost", "answers_total", "switching"}
    assert status["answers_total"] > 0 and status["headline"]
    for o in body["items"]:
        assert {"why", "questions", "success_metric"} <= set(o)


def test_why_without_winners_or_sources_never_shows_an_empty_name():
    why = _why([{"text": "q", "category": "CATEGORY", "engines_lost": 3, "engines_total": 3, "winners": [], "cited_domains": []}], "Groww")
    assert len(why) == 2 and all("  " not in w for w in why)
    assert why[1] == "AI answered without recommending Groww or any competitor you track, and cited no sources."


def test_a_category_that_flips_between_gap_types_stays_the_same_opportunity(client):
    from app.opportunities.models import Opportunity
    from app.common.database import SessionLocal

    headers = signup(client, "flipgap")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    questions = [{"text": "best app", "category": "CATEGORY", "engines_lost": 2, "engines_total": 3,
                  "winners": [{"name": "Upstox", "engines": 2, "reason": None, "quote": None}], "cited_domains": []}]

    def gap(kind):
        return {"type": kind, "title": kind, "description": "d", "recommended_action": "a", "impact": "medium", "confidence": 0.6,
                "evidence": {"category": "CATEGORY", "prompts": ["best app"], "questions": questions, "answers_lost": 2}}

    real = service.detect
    try:
        service.detect = lambda *a, **k: [gap("COMPETITOR_GAP")]
        client.post(f"{API}/projects/{project_id}/scans", headers=headers)
        first = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
        client.patch(f"{API}/projects/{project_id}/opportunities/{first[0]['id']}", json={"status": "in_progress"}, headers=headers)
        service.detect = lambda *a, **k: [gap("CONTENT_GAP")]
        client.post(f"{API}/projects/{project_id}/scans", headers=headers)
        after = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
        service.detect = lambda *a, **k: [gap("COMPETITOR_GAP")]
        client.post(f"{API}/projects/{project_id}/scans", headers=headers)
        back = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    finally:
        service.detect = real
    for rows in (after, back):
        assert len(rows) == 1 and rows[0]["trend"] != "resolved" and rows[0]["trend"] != "new"
        assert rows[0]["status"] == "in_progress" and rows[0]["first_seen_scan_id"] == first[0]["scan_id"]
    assert after[0]["type"] == "CONTENT_GAP" and back[0]["type"] == "COMPETITOR_GAP"
