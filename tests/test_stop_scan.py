"""Stopping a scan: it keeps the answers it saved, drops the rest, charges only for what it saved, and sends no report."""

from sqlalchemy import select, update

from app.common.database import SessionLocal
from app.projects.models import Project
from app.providers.base import AIProvider, AIResponse
from app.providers.models import ModelConfig
from app.providers.registry import ModelRegistry
from app.reports.delivery import deliver_scan_report
from app.reports.models import Report
from app.scans.models import STOPPED_MESSAGE, Scan
from app.scans.service import ScanService
from tests.conftest import API, make_project, signup

ENGINES = ModelRegistry([ModelConfig("chatgpt_search", "good-model", "Good")])


class StopAfterFirstAnswer(AIProvider):
    """Answers every call; the first one also presses "stop", the way the user would mid-scan."""

    def __init__(self, scan_id: int):
        self.scan_id = scan_id
        self.calls = 0

    @property
    def name(self) -> str:
        return "stopper"

    def ask(self, prompt, model, context=None):
        self.calls += 1
        if self.calls == 1:
            with SessionLocal() as session:
                session.execute(update(Scan).where(Scan.id == self.scan_id, Scan.status == "running").values(status="stopping"))
                session.commit()
        return AIResponse(self.name, model, prompt, "1. Halden: great for startups.", {"ok": True})


def _queued_scan(client, headers) -> tuple[str, int]:
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=ENGINES).start_scan(session, project)
        session.commit()
        return project_id, scan.id


def test_a_running_scan_stops_keeps_its_answers_and_charges_only_for_them(client):
    headers = signup(client, "stopmid")
    _, scan_id = _queued_scan(client, headers)
    ScanService(provider=StopAfterFirstAnswer(scan_id), model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "partial" and scan.error_message == STOPPED_MESSAGE
        assert 0 < scan.completed_runs < scan.total_runs
        assert float(scan.credits) == scan.completed_runs  # ChatGPT Search: 1 credit per saved answer
    deliver_scan_report(scan_id, "manual")
    with SessionLocal() as session:
        assert session.scalar(select(Report.id).where(Report.scan_id == scan_id)) is None


def test_stop_endpoint_ends_a_queued_scan_at_once(client):
    headers = signup(client, "stopqueued")
    project_id, scan_id = _queued_scan(client, headers)
    res = client.post(f"{API}/projects/{project_id}/scans/{scan_id}/stop", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "failed" and res.json()["error_message"] == STOPPED_MESSAGE
    assert res.json()["credits"] == 0
    # The runner picking it up afterwards does nothing.
    ScanService(provider=StopAfterFirstAnswer(scan_id), model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        assert session.get(Scan, scan_id).completed_runs == 0


def test_stop_endpoint_marks_a_running_scan_and_blocks_a_new_one_until_it_ends(client):
    headers = signup(client, "stoprunning")
    project_id, scan_id = _queued_scan(client, headers)
    with SessionLocal() as session:
        session.get(Scan, scan_id).status = "running"
        session.commit()
    res = client.post(f"{API}/projects/{project_id}/scans/{scan_id}/stop", headers=headers)
    assert res.status_code == 200 and res.json()["status"] == "stopping"
    assert client.post(f"{API}/projects/{project_id}/scans/{scan_id}/stop", headers=headers).status_code == 200  # pressing twice is fine
    assert client.post(f"{API}/projects/{project_id}/scans", headers=headers).status_code != 200  # still one scan at a time


def test_a_finished_scan_cannot_be_stopped(client):
    headers = signup(client, "stopdone")
    project_id, scan_id = _queued_scan(client, headers)
    with SessionLocal() as session:
        session.get(Scan, scan_id).status = "completed"
        session.commit()
    res = client.post(f"{API}/projects/{project_id}/scans/{scan_id}/stop", headers=headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "SCAN_NOT_RUNNING"


def test_someone_else_cannot_stop_your_scan(client):
    owner = signup(client, "stopowner")
    project_id, scan_id = _queued_scan(client, owner)
    stranger = signup(client, "stopstranger")
    assert client.post(f"{API}/projects/{project_id}/scans/{scan_id}/stop", headers=stranger).status_code == 404
