from sqlalchemy import select

from app.common.database import SessionLocal
from app.projects.models import Project
from app.providers.base import AIProvider, AIResponse
from app.providers.models import ModelConfig
from app.providers.registry import ModelRegistry
from app.scans.models import Scan
from app.scans.service import ScanService
from tests.conftest import API, make_project, signup

ENGINES = ModelRegistry([ModelConfig("good", "good-model", "Good"), ModelConfig("bad", "bad-model", "Bad")])


class FlakyProvider(AIProvider):
    """Fails every call to one engine; answers the other."""

    def __init__(self, fail_models: set[str]):
        self.fail_models = fail_models

    @property
    def name(self) -> str:
        return "flaky"

    def ask(self, prompt, model, context=None):
        if model in self.fail_models:
            raise RuntimeError("provider unavailable")
        return AIResponse(self.name, model, prompt, "1. Halden: great for startups.", {"ok": True})


def _queued_scan(client, headers) -> tuple[str, int]:
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=ENGINES).start_scan(session, project)
        session.commit()
        return project_id, scan.id


def test_one_failing_engine_makes_scan_partial_not_failed(client):
    headers = signup(client, "flaky")
    _, scan_id = _queued_scan(client, headers)
    ScanService(provider=FlakyProvider({"bad-model"}), model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "partial"
        assert scan.completed_runs == scan.failed_runs == scan.total_runs // 2
        assert "provider unavailable" in scan.error_message


def test_all_engines_failing_marks_scan_failed(client):
    headers = signup(client, "down")
    _, scan_id = _queued_scan(client, headers)
    ScanService(provider=FlakyProvider({"good-model", "bad-model"}), model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        assert session.get(Scan, scan_id).status == "failed"


def test_scan_runs_at_most_once(client):
    headers = signup(client, "once")
    _, scan_id = _queued_scan(client, headers)
    service = ScanService(provider=FlakyProvider(set()), model_registry=ENGINES)
    service.run(scan_id)
    service.run(scan_id)  # second call is a no-op: idempotent
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.completed_runs == scan.total_runs


def test_cannot_start_two_scans_at_once(client):
    headers = signup(client, "busy")
    project_id, _ = _queued_scan(client, headers)  # left queued, not run
    second = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SCAN_ALREADY_RUNNING"


def test_scan_requires_active_prompts(client):
    headers = signup(client, "noprompts")
    project_id = make_project(client, headers)
    response = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_ACTIVE_PROMPTS"
