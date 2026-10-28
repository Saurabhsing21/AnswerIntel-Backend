"""The PDF report: what each page says (rules in document.py), and the report worker that draws it ahead of time."""

import re
import shutil

import pytest

from app.common.database import SessionLocal
from app.reports import pdf_jobs
from app.reports.document import build_document, wilson
from app.reports.models import ReportPdf
from tests.conftest import API
from tests.test_reports import ready_project, run_scan

REAL_RENDER = pdf_jobs.render_pdf_bytes  # captured before the conftest stub replaces it

VIS = {"mention_rate": 0.0, "recommendation_rate": 0.0, "share_of_voice": 0.0, "citation_rate": 0.0,
       "positive_sentiment_rate": None, "average_position": None, "total_responses": 30, "deltas": {}}
CONTENT = {
    "brand": "Bachatt", "website": "https://bachatt.app/", "category": "micro investing", "visibility": VIS,
    "engines": [{"key": "chatgpt", "name": "ChatGPT", "responses": 30, "mention_rate": 0.0, "recommendation_rate": 0.0}],
    "competitors": [
        {"name": "Bachatt", "is_you": True, "mention_rate": 0.0, "recommendation_rate": 0.0, "share_of_voice": 0.0},
        {"name": "Groww", "is_you": False, "mention_rate": 0.7, "recommendation_rate": 0.67, "share_of_voice": 0.74, "average_position": 1.2},
        {"name": "Jar", "is_you": False, "mention_rate": 0.13, "recommendation_rate": 0.03, "share_of_voice": 0.04},
    ],
    "questions": [
        {"text": "Best micro investing apps in India?", "category": "CATEGORY", "recommended_on": 0, "seen_on": 0, "picked": ["Groww"]},
        {"text": "Alternative to Jar for saving?", "category": "ALTERNATIVE", "recommended_on": 0, "seen_on": 0, "picked": ["Groww", "Jar"]},
        {"text": "Why am I losing money to bank charges?", "category": "PROBLEM", "recommended_on": 0, "seen_on": 0, "picked": []},
        {"text": "बचत के लिए सबसे अच्छा ऐप कौन सा है?", "category": "USE_CASE", "recommended_on": 0, "seen_on": 0, "picked": []},
    ],
    "sources": [],
    "competitor_reasons": {"Groww": {"reasons": [{"text": "Strong for mutual funds", "count": 5}], "quote": "Strong for mutual funds."}},
    "meta": {"country": "IN", "engines": ["ChatGPT"], "scans_in_trend": 1,
             "generated_at": "2026-10-27T15:32:00+00:00", "scan_started_at": "2026-10-27T15:30:00+00:00"},
}


def test_open_questions_come_last_and_drive_the_first_action():
    doc = build_document(CONTENT)
    assert [r["open"] for r in doc["question_rows"]] == [False, False, True, True]
    assert doc["open_count"] == 2 and [r["n"] for r in doc["open_rows"]] == [3, 4]
    assert doc["actions"][0]["title"] == "Answer the 2 open questions" and doc["actions"][0]["targets"] == "Q3, Q4"
    assert doc["actions"][1]["title"] == "Publish /bachatt-vs-groww"
    assert doc["do_first"] == doc["actions"][0]


def test_scores_ranges_and_wording_come_from_the_numbers():
    doc = build_document(CONTENT)
    assert doc["score"] == 0 and doc["score_label"] == "NOT VISIBLE"
    assert doc["leader"]["name"] == "Groww" and doc["metrics"][0]["range"] == "0–11%"  # 0 of 30, Wilson 95%
    lo, hi = wilson(0.67, 30)
    assert round(lo, 2) == 0.49 and round(hi, 2) == 0.81
    assert doc["summary"][0]["lead"] == "Bachatt is not yet visible in AI answers."
    assert doc["generated"].endswith("IST") and doc["scan_date"] == "27 Oct 2026"
    assert [s["label"] for s in doc["stages"]] == ["Problem", "Discovery", "Use case", "Alternatives"]
    assert doc["competitor_why"][0]["items"][0]["title"] == "Strong for mutual funds"
    assert doc["claims"] == [{"claim": "Strong for mutual funds", "competitor": "Groww", "page": "Homepage hero and FAQ"}]
    assert "Google AI Mode" in [e["name"] for e in doc["engine_rows"] if not e["scanned"]]


def test_reports_saved_before_the_pdf_rules_still_build():
    old = {k: v for k, v in CONTENT.items() if k not in ("competitor_reasons", "meta")}
    old["questions"] = [{"text": "q", "category": "CATEGORY", "recommended_on": 0, "seen_on": 1, "winners": ["Groww"]}]
    doc = build_document(old)
    assert doc["question_rows"][0]["you"] == "NAMED" and doc["question_rows"][0]["picked"] == ["Groww"]


def test_a_new_report_has_its_pdf_drawn_once_and_served_from_storage(client):
    headers, project_id = ready_project(client, "pdfjob")
    run_scan(client, headers, project_id)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "manual"}, headers=headers).json()
    assert report["pdf_status"] == "pending"  # the response does not wait for the PDF

    base = f"{API}/projects/{project_id}/reports/{report['id']}"
    assert client.get(base, headers=headers).json()["pdf_status"] == "ready"
    pdf = client.get(f"{base}/export?format=pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content == b"%PDF-1.7 stub"
    assert "AI Visibility Report" in pdf.headers["content-disposition"]
    listed = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert all(r["pdf_status"] == "ready" for r in listed)  # the scan's own report got one too
    assert 0 <= listed[0]["headline"]["score"] <= 100 and "mention_rate" in listed[0]["headline"]


def test_a_failed_pdf_is_retried_when_someone_asks_for_it(client, monkeypatch):
    headers, project_id = ready_project(client, "pdffail")
    run_scan(client, headers, project_id)

    def broken(document):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr(pdf_jobs, "render_pdf_bytes", broken)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "manual"}, headers=headers).json()
    base = f"{API}/projects/{project_id}/reports/{report['id']}"
    with SessionLocal() as session:
        row = session.get(ReportPdf, report["id"])
        assert row.status == "failed" and "renderer crashed" in row.error

    monkeypatch.setattr(pdf_jobs, "render_pdf_bytes", lambda document: b"%PDF-1.7 again")
    waiting = client.get(f"{base}/export?format=pdf", headers=headers)
    assert waiting.status_code == 202 and waiting.json() == {"status": "pending"}
    assert client.get(f"{base}/export?format=pdf", headers=headers).content == b"%PDF-1.7 again"


@pytest.mark.skipif(not shutil.which("node") or not pdf_jobs.RENDERER.exists(), reason="build pdf-renderer first: npm run build")
def test_the_renderer_draws_every_section_and_prints_hindi():
    pdf = REAL_RENDER(build_document(CONTENT))
    assert pdf.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 13  # cover, contents and eleven sections
    assert b"NotoSansDevanagari" in pdf  # the Hindi question used the fallback font
