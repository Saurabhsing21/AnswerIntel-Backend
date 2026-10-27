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
    monkeypatch.setattr("app.reports.delivery.send_report_email", lambda to, subject, html: sent.append((to, subject)))
    return sent


def test_a_manual_scan_creates_and_emails_a_report(client, outbox, monkeypatch):
    sent = report_inbox(monkeypatch)
    headers, project_id = ready(client, "autorep")
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()

    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert len(reports) == 1
    assert reports[0]["scan_id"] == scan["id"] and reports[0]["type"] == "manual" and reports[0]["emailed_at"]
    assert len(sent) == 1 and sent[0][1].startswith("Halden")
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
