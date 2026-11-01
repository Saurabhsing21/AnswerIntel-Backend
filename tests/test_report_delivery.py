"""Every finished scan leaves a report behind: paid workspaces get it created and emailed; the free trial does not."""

from app.common.database import SessionLocal
from app.reports.delivery import deliver_scan_report
from app.reports.models import Report
from tests.conftest import API, make_project, signup
from tests.test_free_trial import verify


def ready(client, prefix):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def report_inbox(monkeypatch):
    sent = []
    monkeypatch.setattr("app.reports.delivery.send_report_email", lambda to, subject, html, attachments=None: sent.append((to, subject, attachments)))
    return sent


def test_a_manual_scan_creates_and_emails_a_report(client, outbox, monkeypatch):
    sent = report_inbox(monkeypatch)
    headers, project_id = ready(client, "autorep")
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()

    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert len(reports) == 1
    assert reports[0]["scan_id"] == scan["id"] and reports[0]["type"] == "manual" and reports[0]["emailed_at"]
    assert len(sent) == 1 and sent[0][1].startswith("Halden")
    assert sent[0][2][0][0].endswith(".pdf") and sent[0][2][0][1].startswith(b"%PDF")  # the PDF was ready: attached
    # The report email is the "your scan is ready" email for paid accounts: one email, not two.
    assert not [m for m in outbox if "is ready" in m["subject"]]


def test_every_scan_gets_its_own_report_once(client, monkeypatch):
    report_inbox(monkeypatch)
    headers, project_id = ready(client, "autorep2")
    first = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    second = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    deliver_scan_report(second["id"], "manual")  # a redelivered job must not duplicate it

    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert sorted(r["scan_id"] for r in reports) == [first["id"], second["id"]]


def test_a_report_is_kept_when_email_is_not_configured(client):
    headers, project_id = ready(client, "autorep3")
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert len(reports) == 1 and reports[0]["emailed_at"] is None


def test_the_free_trial_gets_the_ready_email_and_no_report(client, outbox, monkeypatch, trial_signups):
    sent = report_inbox(monkeypatch)
    headers, project_id = ready(client, "autorepfree")
    verify(client, outbox, headers)
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()

    with SessionLocal() as session:
        assert session.query(Report).filter(Report.scan_id == scan["id"]).count() == 0
    assert not sent
    assert [m["subject"] for m in outbox if "is ready" in m["subject"]] == ["Your first scan of Halden is ready"]


def test_the_report_email_attaches_the_pdf_or_links_when_it_is_not_ready(client, monkeypatch):
    sent = report_inbox(monkeypatch)
    monkeypatch.setattr("app.reports.delivery.queue_report_pdf", lambda report_id: None)  # the worker has not finished
    headers, project_id = ready(client, "autorep4")
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert len(sent) == 1 and not sent[0][2]
    report = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()[0]
    from app.reports.email_render import build_report_email
    with SessionLocal() as session:
        _, html, _ = build_report_email(session, session.get(Report, report["id"]))
    assert f"/projects/{project_id}/reports/{report['id']}" in html and "attached as a PDF" not in html
    assert "estimate" in html and "DO THIS FIRST" in html and "Key findings" in html


def test_resend_gets_the_pdf_as_base64(monkeypatch):
    import base64

    from app.common.config import settings
    from app.reports.email import send_report_email

    captured = {}

    class Ok:
        status_code = 200

    monkeypatch.setattr(settings, "resend_api_key", "key")
    monkeypatch.setattr("app.reports.email.httpx.post", lambda url, json, **kw: captured.update(json) or Ok())
    send_report_email("a@example.com", "s", "<p>x</p>", [("r.pdf", b"%PDF-1")])
    assert captured["attachments"] == [{"filename": "r.pdf", "content": base64.b64encode(b"%PDF-1").decode()}]


def test_the_pdf_is_read_from_r2_when_it_lives_there(client, monkeypatch):
    headers, project_id = ready(client, "autorep5")
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    report_id = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()[0]["id"]
    from app.reports.email_render import build_report_email
    from app.reports.models import ReportPdf
    monkeypatch.setattr("app.reports.email_render.storage.get_pdf", lambda key: b"%PDF-from-r2")
    with SessionLocal() as session:
        row = session.get(ReportPdf, report_id)
        row.storage_key, row.pdf = f"reports/{project_id}/{report_id}.pdf", None
        _, _, attachments = build_report_email(session, session.get(Report, report_id))
    assert attachments[0][1] == b"%PDF-from-r2"
