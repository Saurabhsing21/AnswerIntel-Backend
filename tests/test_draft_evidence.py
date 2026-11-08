"""Drafts are written from the evidence behind the gap: the AI's own quotes, the pages it cited, the steps."""

from types import SimpleNamespace

from app.opportunities import draft
from app.opportunities.draft import EVIDENCE_LIMIT, draft_for

QUOTE = "Kiteline has the lowest fees of any CRM we tested."
PAGE = "https://www.g2.com/categories/crm"
PROJECT = SimpleNamespace(brand_name="Halden", website="https://halden.co", category="CRM software", country="US",
                          description="CRM for startups", workspace_id=None, id=None, user_id=None)


def opportunity(evidence):
    return SimpleNamespace(title="AI picks Kiteline over Halden", description="Lost 3 answers.",
                           recommended_action="Publish a comparison page.", evidence=evidence)


def sent(monkeypatch, evidence):
    """The messages draft_for sends to the model, with the AI call captured instead of made."""
    calls = []

    def fake_chat(model, messages, **kwargs):
        calls.append(messages)
        return {"choices": [{"message": {"content": "# Draft"}}]}

    monkeypatch.setattr(draft, "chat", fake_chat)
    assert draft_for(PROJECT, opportunity(evidence)) == {"markdown": "# Draft"}
    system, user = calls[0]
    return system["content"], user["content"]


EVIDENCE = {
    "prompts": ["Which CRM has the lowest fees?"],
    "why": [f'AI picked Kiteline in 3 answers (summary: low fees): "{QUOTE}"'],
    "questions": [{
        "text": "Which CRM has the lowest fees?",
        "winners": [{"name": "Kiteline", "engines": 3, "reason": "low fees", "quote": QUOTE}],
        "cited_pages": [{"url": PAGE, "domain": "g2.com", "source_type": "review_site", "competitor_id": None, "count": 2}],
        "response_ids": [1, 2, 3],
    }],
    "steps": ["Write a comparison page answering \"Which CRM has the lowest fees?\"."],
    "success_metric": "At the next scan, AI should name Halden in at least a third of these answers.",
}


def test_the_draft_prompt_carries_the_quotes_pages_steps_and_success_metric(monkeypatch):
    system, user = sent(monkeypatch, EVIDENCE)
    assert f'"{QUOTE}"' in user and "Kiteline" in user and "low fees" in user
    assert PAGE in user
    assert "Write a comparison page" in user and "At the next scan, AI should name Halden" in user
    assert "AI picked Kiteline in 3 answers" in user
    assert "no invented facts" in system and "[placeholder]" in system  # the rules for the writer are unchanged


def test_citation_gap_pages_are_listed(monkeypatch):
    _, user = sent(monkeypatch, {"pages": [{"url": PAGE, "domain": "g2.com", "source_type": "review_site", "count": 4}]})
    assert PAGE in user


def test_missing_or_odd_evidence_does_not_crash_the_draft(monkeypatch):
    for evidence in ({}, None, {"questions": None, "steps": "text", "why": None},
                     {"questions": [{"text": "q"}, {"winners": [{"name": "Kiteline"}]}, "oops"]}):
        _, user = sent(monkeypatch, evidence)
        assert "Recommended action: Publish a comparison page." in user


def test_a_long_evidence_block_is_cut_between_items_never_inside_a_quote(monkeypatch):
    quotes = [f"Competitor {i} is the best CRM for teams because of reason number {i}. " * 3 for i in range(60)]
    evidence = {**EVIDENCE, "questions": [{"text": f"Question {i}?", "winners": [{"name": f"Rival {i}", "engines": 2,
                "reason": "r", "quote": q.strip()}], "cited_pages": []} for i, q in enumerate(quotes)]}
    _, user = sent(monkeypatch, evidence)
    block = user[user.index("Evidence"):]
    assert len(block) <= EVIDENCE_LIMIT + 400  # the block plus its closing instruction
    assert QUOTE not in user or f'"{QUOTE}"' in user
    for line in block.splitlines():
        if '"' in line and "Competitor" in line:
            assert line.count('"') % 2 == 0 and line.rstrip().endswith('"')  # a quote that is shown is whole
    assert "At the next scan, AI should name Halden" in user  # what to check later outranks the long tail of quotes
