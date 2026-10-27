import re

from app.reports.pdf import render_pdf

VIS = {"mention_rate": 0.4, "recommendation_rate": 0.2, "share_of_voice": 0.3, "citation_rate": 0.1,
       "positive_sentiment_rate": 0.5, "average_position": 2.0, "deltas": {}, "margins": {"mention_rate": 0.1}}
BASE = {"brand": "Acme", "website": "https://acme.test", "category": "crm", "visibility": VIS, "engines": [],
        "competitors": [], "top_opportunities": [], "trend": [], "summary": ["Acme was mentioned in 40% of AI answers."]}


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def test_reports_saved_before_the_new_sections_still_render():
    assert render_pdf(BASE, "Acme: AI visibility report").startswith(b"%PDF")


def test_a_full_report_is_a_few_pages_and_prints_hindi():
    content = {**BASE,
               "engines": [{"name": "ChatGPT", "responses": 5, "mention_rate": 0.4, "recommendation_rate": 0.2}],
               "competitors": [{"name": "Acme", "is_you": True, "mention_rate": 0.4, "recommendation_rate": 0.2, "share_of_voice": 0.3, "average_position": 2.0},
                               {"name": "Rival", "is_you": False, "mention_rate": 0.8, "recommendation_rate": 0.6, "share_of_voice": 0.7, "average_position": 1.0}],
               "questions": [{"text": "भारत में सबसे अच्छा CRM कौन सा है?", "status": "absent", "recommended_on": 0, "engines": 5, "winners": ["Rival"]}],
               "sources": [{"domain": "g2.com", "citations": 3, "with_you": 0, "source_type": "review_site", "owner": None}],
               "top_opportunities": [{"title": "Rival wins 3 questions", "description": "d", "recommended_action": "a", "impact": "high", "effort": "M", "steps": ["Do this"]}],
               "meta": {"scan_id": 1, "engines": ["ChatGPT"], "questions": 1, "answers": 5, "country": "India",
                        "generated_at": "2026-10-27T08:00:00+00:00", "scan_completed_at": "2026-10-27T07:00:00+00:00"}}
    pdf = render_pdf(content, "Acme: AI visibility report", "20 Oct – 27 Oct 2026")
    assert 3 <= pages(pdf) <= 6
    assert b"NotoSansDevanagari" in pdf  # the Hindi question used the fallback font, not "?"
