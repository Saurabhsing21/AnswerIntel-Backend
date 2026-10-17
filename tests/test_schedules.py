"""PRD sections 81-82: weekly schedule, scheduler that only queues work, stuck-scan sweeper."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.common.config import settings
from app.common.database import SessionLocal
from app.reports.models import Report
from app.scans.models import Scan
from app.schedules.models import ScanSchedule
from app.schedules.service import dispatch_due_scans, requeue_stuck_scans
from tests.conftest import API, make_project, signup


def project_with_prompts(client, prefix="sched"):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def enable(client, headers, project_id, day_of_week=0, hour=9):
    return client.put(
        f"{API}/projects/{project_id}/schedule",
        json={"enabled": True, "day_of_week": day_of_week, "hour": hour},
        headers=headers,
    )


def created_at(project_id) -> datetime:
    with SessionLocal() as session:
        return session.scalar(select(ScanSchedule.created_at).where(ScanSchedule.project_id == project_id))


def mine(scan_ids: list[int], project_id) -> list[int]:
    """The dispatcher serves every project in the shared test database; keep only this project's scans."""
    with SessionLocal() as session:
        return [s for s in scan_ids if session.get(Scan, s).project_id == uuid.UUID(project_id)]


def next_slot(after: datetime, day_of_week: int, hour: int) -> datetime:
    """The first moment after `after` + 1 hour that falls on the given weekday and hour."""
    slot = (after + timedelta(days=1)).replace(hour=hour, minute=5, second=0, microsecond=0)
    while slot.weekday() != day_of_week:
        slot += timedelta(days=1)
    return slot


def test_schedule_api_defaults_validation_and_privacy(client):
    headers, project_id = project_with_prompts(client)
    default = client.get(f"{API}/projects/{project_id}/schedule", headers=headers).json()
    assert default == {"enabled": False, "frequency": "weekly", "day_of_week": 0, "hour": 9, "last_run_at": None}

    saved = enable(client, headers, project_id, day_of_week=3, hour=14)
    assert saved.status_code == 200 and saved.json()["enabled"] is True
    assert client.get(f"{API}/projects/{project_id}/schedule", headers=headers).json()["day_of_week"] == 3

    assert enable(client, headers, project_id, hour=24).status_code == 422
    assert enable(client, headers, project_id, day_of_week=7).status_code == 422
    off = client.put(f"{API}/projects/{project_id}/schedule", json={"enabled": False}, headers=headers)
    assert off.json()["enabled"] is False and off.json()["day_of_week"] == 3  # unspecified fields keep their value

    stranger = signup(client, "schedstranger")
    assert client.get(f"{API}/projects/{project_id}/schedule", headers=stranger).status_code == 404
    assert client.put(f"{API}/projects/{project_id}/schedule", json={"enabled": True}, headers=stranger).status_code == 404


def test_scheduler_only_queues_scans_once_per_slot(client):
    headers, project_id = project_with_prompts(client, "dispatch")
    enable(client, headers, project_id, day_of_week=2, hour=10)
    queued: list[tuple[int, bool]] = []

    def enqueue(scan_id, send_report):
        queued.append((scan_id, send_report))

    # Right after enabling, the slot has not come round yet.
    assert mine(dispatch_due_scans(created_at(project_id) + timedelta(minutes=1), enqueue), project_id) == []

    slot = next_slot(created_at(project_id), 2, 10)
    started = mine(dispatch_due_scans(slot, enqueue), project_id)
    assert len(started) == 1 and (started[0], True) in queued  # the scheduler queues; it does not run the scan
    with SessionLocal() as session:
        assert session.get(Scan, started[0]).status == "queued"

    # Same slot again: no duplicate scan for this project.
    assert mine(dispatch_due_scans(slot + timedelta(minutes=30), enqueue), project_id) == []


def test_disabled_schedule_never_dispatches(client):
    headers, project_id = project_with_prompts(client, "off")
    enable(client, headers, project_id, day_of_week=2, hour=10)
    client.put(f"{API}/projects/{project_id}/schedule", json={"enabled": False}, headers=headers)
    assert mine(dispatch_due_scans(next_slot(created_at(project_id), 2, 10), lambda *_: None), project_id) == []


def test_a_blocked_slot_is_retried_on_the_next_run(client):
    headers, project_id = project_with_prompts(client, "retryslot")
    enable(client, headers, project_id, day_of_week=2, hour=10)
    slot = next_slot(created_at(project_id), 2, 10)

    client.post(f"{API}/projects/{project_id}/scans", headers=headers)  # a manual scan is active/finished
    with SessionLocal() as session:
        session.execute(update(Scan).where(Scan.project_id == project_id).values(status="running"))
        session.commit()
    assert mine(dispatch_due_scans(slot, lambda *_: None), project_id) == []  # blocked by the running scan, nothing lost

    with SessionLocal() as session:
        session.execute(update(Scan).where(Scan.project_id == project_id).values(status="completed"))
        session.commit()
    assert len(mine(dispatch_due_scans(slot + timedelta(hours=1), lambda *_: None), project_id)) == 1  # one run later


def test_stuck_queued_scans_are_requeued(client):
    headers, project_id = project_with_prompts(client, "stuck")
    stuck = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()["id"]
    # In tests the scan already ran in-process; put it back into the "lost job" state.
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=30)
    with SessionLocal() as session:
        session.execute(update(Scan).where(Scan.id == stuck).values(status="queued", created_at=long_ago))
        session.commit()

    # The shared test database may hold other old queued scans; only this scan is asserted on.
    requeued: list[int] = []
    assert stuck in requeue_stuck_scans(datetime.now(timezone.utc), lambda scan_id: requeued.append(scan_id))
    assert stuck in requeued

    with SessionLocal() as session:
        session.execute(update(Scan).where(Scan.id == stuck).values(created_at=datetime.now(timezone.utc)))
        session.commit()
    assert stuck not in requeue_stuck_scans(datetime.now(timezone.utc), lambda scan_id: None)  # too fresh


def test_scheduled_scan_produces_and_emails_the_weekly_report(client, monkeypatch):
    from app.worker.tasks import run_scan_task

    headers, project_id = project_with_prompts(client, "weekly")
    sent = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr("app.reports.email.httpx.post", lambda url, json, headers, timeout: sent.append(json) or FakeResponse())

    with SessionLocal() as session:
        from app.projects.models import Project
        from app.scans.service import ScanService

        scan = ScanService().start_scan(session, session.get(Project, project_id))
        session.commit()
        scan_id = scan.id

    assert run_scan_task.apply(args=[scan_id, True]).successful()
    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert len(reports) == 1 and reports[0]["type"] == "weekly" and reports[0]["emailed_at"] is not None
    assert len(sent) == 1 and sent[0]["to"][0].endswith("@example.com")


def test_scheduled_report_without_email_configured_still_succeeds(client, monkeypatch):
    from app.worker.tasks import run_scan_task

    headers, project_id = project_with_prompts(client, "noemail")
    monkeypatch.setattr(settings, "resend_api_key", "")
    with SessionLocal() as session:
        from app.projects.models import Project
        from app.scans.service import ScanService

        scan_id = ScanService().start_scan(session, session.get(Project, project_id)).id
        session.commit()

    assert run_scan_task.apply(args=[scan_id, True]).successful()
    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert len(reports) == 1 and reports[0]["emailed_at"] is None  # report kept, email skipped
