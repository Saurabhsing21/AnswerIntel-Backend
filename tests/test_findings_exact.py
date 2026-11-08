"""Findings carry exact quotes, exact pages and steps that fit the sources AI used."""

import re

from app.metrics.service import Observation
from app.opportunities.service import TOPICS, detect
from tests.conftest import API, make_project, signup

COMPETITORS = {1: "Kiteline", 2: "Vantor"}
ENGINES = ("chatgpt", "perplexity", "gemini")
QUOTE = "Kiteline has the lowest fees of any CRM we tested."


def cite(url, source_type, competitor_id=None):
    domain = re.sub(r"^www\.", "", url.split("/")[2])
    return {"url": url, "domain": domain, "source_type": source_type, "is_brand_owned": False, "competitor_id": competitor_id}


def answer(n, engine, q, lost, text, category="CATEGORY", reason="low fees", quote=QUOTE, cites=(), winner=1):
    return Observation(
        response_id=n, engine=engine, scan_prompt_id=q, prompt_id=q, prompt_text=text, category=category,
        brand={"mentioned": not lost, "recommended": not lost, "position": None, "sentiment": None},
        competitors={winner: {"mentioned": True, "recommended": True, "position": 1, "sentiment": "positive",
                              "reason": reason, "evidence": quote}} if lost else {},
        citations=list(cites) if lost else [],
    )


def asked(q, text, lost_on=ENGINES, start=0, **kw):
    return [answer(start + i, e, q, e in lost_on, text, **kw) for i, e in enumerate(ENGINES)]


def won(n=4, start=900):
    return [answer(start + i * 3 + j, e, 500 + i, False, f"won question {i}") for i in range(n) for j, e in enumerate(ENGINES)]


def gaps(rows, **kw):
    return {(f["type"], f["evidence"].get("category")): f for f in detect(rows, "Halden", COMPETITORS, **kw)}


# ---- quotes ---------------------------------------------------------------------------------------------------

def test_only_verified_quotes_are_in_quotation_marks_and_reasons_are_labelled_summaries():
    rows = asked(1, "Which CRM has the lowest fees?") + asked(2, "Best CRM for agencies?", quote=None, start=10, winner=2,
                                                              reason="built for agencies") + won()
    gap = gaps(rows)[("COMPETITOR_GAP", "CATEGORY")]
    why = gap["evidence"]["why"]
    assert f'AI picked Kiteline in 3 answers (summary: low fees): "{QUOTE}"' in why
    assert "AI picked Vantor in 3 answers (summary: built for agencies)." in why
    # Nothing in quotation marks anywhere in why or steps that is not the AI's own words (or the user's question).
    questions = {"Which CRM has the lowest fees?", "Best CRM for agencies?"}
    for line in why + gap["evidence"]["steps"]:
        for quoted in re.findall(r'"([^"]+)"', line):
            assert quoted in (QUOTE, *questions), line


# ---- exact pages ----------------------------------------------------------------------------------------------

def test_citation_gap_lists_the_exact_pages_alongside_domains():
    g2 = cite("https://www.g2.com/categories/crm", "review_site")
    thread = cite("https://www.reddit.com/r/sales/comments/abc/best_crm", "reddit")
    rows = asked(1, "Best CRM?", cites=[g2, thread]) + asked(2, "Top CRM?", start=10, cites=[g2]) + won()
    gap = gaps(rows)[("CITATION_GAP", None)]
    assert gap["evidence"]["domains"] == [{"domain": "g2.com", "citations": 6}, {"domain": "reddit.com", "citations": 3}]
    assert gap["evidence"]["pages"] == [
        {"url": "https://www.g2.com/categories/crm", "domain": "g2.com", "source_type": "review_site", "count": 6},
        {"url": "https://www.reddit.com/r/sales/comments/abc/best_crm", "domain": "reddit.com", "source_type": "reddit", "count": 3},
    ]
    many = [cite(f"https://www.g2.com/p/{i}", "review_site") for i in range(10)]
    assert len(gaps(asked(1, "Best CRM?", cites=many) + won())[("CITATION_GAP", None)]["evidence"]["pages"]) == 8


def test_steps_follow_the_type_of_source_ai_cited():
    pages = {
        "review_site": cite("https://www.g2.com/categories/crm", "review_site"),
        "reddit": cite("https://www.reddit.com/r/sales/comments/abc/best_crm", "reddit"),
        "news": cite("https://techcrunch.com/2026/crm-funding", "news"),
        "directory": cite("https://www.producthunt.com/categories/crm", "directory"),
        "comparison": cite("https://acme.io/kiteline-vs-vantor", "comparison"),
        "blog": cite("https://blog.acme.io/best-crms", "blog"),
        "competitor_website": cite("https://kiteline.com/why-kiteline", "competitor_website", competitor_id=1),
    }
    expected = {
        "review_site": "Get Halden reviewed on g2.com",
        "reddit": "Answer in the Reddit thread AI cited",
        "news": "Pitch the author",
        "directory": "Submit a listing for Halden on producthunt.com",
        "comparison": "Ask the author of https://acme.io/kiteline-vs-vantor to add Halden",
        "blog": "Ask the author of https://blog.acme.io/best-crms to add Halden",
        "competitor_website": "Publish a page comparing Halden with Kiteline",
    }
    for kind, page in pages.items():
        rows = asked(1, "Best CRM?", cites=[page]) + asked(2, "Top CRM?", start=10, cites=[page]) + won()
        found = gaps(rows)
        question_steps = found[("COMPETITOR_GAP", "CATEGORY")]["evidence"]["steps"]
        step = next((s for s in question_steps if s.startswith(expected[kind])), None)
        assert step and page["url"] in step, (kind, question_steps)
        if kind != "competitor_website":  # a competitor's own site is never a third-party source
            citation_steps = found[("CITATION_GAP", None)]["evidence"]["steps"]
            assert any(s.startswith(expected[kind]) and page["url"] in s for s in citation_steps), (kind, citation_steps)


# ---- topics ---------------------------------------------------------------------------------------------------

def test_topic_steps_are_industry_neutral_and_match_whole_words_only():
    for _, step in TOPICS:
        for word in ("regulator", "licence", "license", "brokerage", "customer money"):
            assert word not in step.lower()
    finance = asked(1, "Which broker has the lowest brokerage and is safe?", reason="trusted, with low fees") + won()
    steps = " ".join(gaps(finance)[("COMPETITOR_GAP", "CATEGORY")]["evidence"]["steps"])
    assert "pricing page" in steps and "trust page" in steps
    # "feedback" is not "fee", "costume" is not "cost", "supportive" is not "support".
    near_misses = asked(1, "Which CRM gets the best user feedback for costume shops?", reason="supportive community") + won()
    steps = " ".join(gaps(near_misses)[("COMPETITOR_GAP", "CATEGORY")]["evidence"]["steps"])
    assert "pricing page" not in steps and "customer support page" not in steps


# ---- ranking by buyer value -----------------------------------------------------------------------------------

def test_questions_and_gaps_rank_by_importance_weighted_answers_lost():
    rows = (asked(1, "Cheap CRM?") + asked(2, "Enterprise CRM?", lost_on=("chatgpt", "gemini"), start=10)
            + asked(3, "Agency CRM?", category="USE_CASE", lost_on=("chatgpt", "gemini"), start=20)
            + asked(4, "Startup CRM?", category="USE_CASE", lost_on=("chatgpt", "gemini"), start=30) + won(1))
    importance = {1: 0.1, 2: 0.9, 3: 0.2, 4: None}
    found = gaps(rows, importance=importance)
    category = found[("COMPETITOR_GAP", "CATEGORY")]["evidence"]
    # 2 lost x 0.9 beats 3 lost x 0.1; a prompt without importance counts as 0.5.
    assert [(q["text"], q["importance"]) for q in category["questions"]] == [("Enterprise CRM?", 0.9), ("Cheap CRM?", 0.1)]
    assert category["weighted_answers_lost"] == 2.1
    assert [q["importance"] for q in found[("COMPETITOR_GAP", "USE_CASE")]["evidence"]["questions"]] == [0.5, 0.2]

    def order(weights):
        return [(f["evidence"]["category"], f["impact"]) for f in detect(rows, "Halden", COMPETITORS, importance=weights)
                if f["type"] == "COMPETITOR_GAP"]

    # Both high and unconfirmed: CATEGORY (5 lost, worth 2.1) before USE_CASE (4 lost, worth 1.4)...
    assert order(importance) == [("CATEGORY", "high"), ("USE_CASE", "high")]
    # ...until USE_CASE's questions matter more: 4 x 1.0 beats 5 lost on low-value questions.
    assert order({1: 0.1, 2: 0.1, 3: 1.0, 4: 1.0}) == [("USE_CASE", "high"), ("CATEGORY", "high")]


def test_question_rows_link_to_their_lost_answers():
    rows = asked(1, "Best CRM?", lost_on=("chatgpt", "gemini"), start=40) + won()
    question = gaps(rows)[("COMPETITOR_GAP", "CATEGORY")]["evidence"]["questions"][0]
    assert question["response_ids"] == [40, 42]


def test_stored_question_rows_carry_the_prompts_importance(client):
    from uuid import UUID

    from sqlalchemy import update

    from app.common.database import SessionLocal
    from app.prompts.models import Prompt

    headers = signup(client, "importance")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as s:
        s.execute(update(Prompt).where(Prompt.project_id == UUID(project_id)).values(importance=0.8))
        s.commit()
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    rows = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    questions = [q for o in rows for q in o["questions"]]
    assert questions and all(q["importance"] == 0.8 and q["response_ids"] for q in questions)
