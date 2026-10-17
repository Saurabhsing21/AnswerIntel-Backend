"""PRD sections 56-61: queue, idempotency, retry backoff, provider rate limits, scan limits."""

import threading
import time
from collections import Counter

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.common.config import settings
from app.common.database import SessionLocal
from app.projects.models import Project
from app.providers.base import AIProvider, AIResponse
from app.providers.models import ModelConfig
from app.providers.registry import ModelRegistry
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.scans.service import ScanService
from tests.conftest import API, make_project, signup

ENGINES = ModelRegistry([ModelConfig("good", "good-model", "Good"), ModelConfig("bad", "bad-model", "Bad")])


class CountingProvider(AIProvider):
    """Fails each (prompt, model) call `fail_first` times, then answers. Tracks concurrency per model."""

    def __init__(self, fail_first: int = 0, hold: float = 0.0):
        self.fail_first = fail_first
        self.hold = hold
        self.calls: Counter = Counter()
        self.active: Counter = Counter()
        self.peak: Counter = Counter()
        self.lock = threading.Lock()

    @property
    def name(self) -> str:
        return "counting"

    def ask(self, prompt, model, context=None):
        with self.lock:
            self.calls[(prompt, model)] += 1
            attempt = self.calls[(prompt, model)]
            self.active[model] += 1
            self.peak[model] = max(self.peak[model], self.active[model])
        try:
            time.sleep(self.hold)
            if attempt <= self.fail_first:
                raise RuntimeError("temporary outage")
            return AIResponse(self.name, model, prompt, "1. Halden: great for startups.", {"ok": True})
        finally:
            with self.lock:
                self.active[model] -= 1


def queued_scan(client, headers, prefix_engines=ENGINES) -> int:
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=prefix_engines).start_scan(session, project)
        session.commit()
        return scan.id


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr("app.scans.execution._backoff", recorded.append)
    return recorded


def test_failed_calls_retry_with_prd_backoff(client, sleeps):
    scan_id = queued_scan(client, signup(client, "retry"))
    provider = CountingProvider(fail_first=3)  # fails 3 times, succeeds on the 4th attempt
    ScanService(provider=provider, model_registry=ENGINES).run(scan_id)

    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "completed" and scan.failed_runs == 0
    assert set(provider.calls.values()) == {4}
    assert {30, 120, 600} <= set(sleeps)  # 30 s, 2 min, 10 min (PRD 59)


def test_retries_exhausted_marks_the_call_failed(client, sleeps):
    scan_id = queued_scan(client, signup(client, "exhaust"))
    provider = CountingProvider(fail_first=99)
    ScanService(provider=provider, model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "failed" and scan.completed_runs == 0
    assert set(provider.calls.values()) == {4}  # first try plus three retries, never more


def test_database_rejects_duplicate_observations(client):
    scan_id = queued_scan(client, signup(client, "dupe"))
    ScanService(provider=CountingProvider(), model_registry=ENGINES).run(scan_id)
    with SessionLocal() as session:
        original = session.scalar(select(AIResponseRecord).where(AIResponseRecord.scan_id == scan_id))
        session.add(AIResponseRecord(
            scan_id=scan_id, scan_prompt_id=original.scan_prompt_id, engine=original.engine, provider="x",
            model="x", prompt="x", response_text="x", raw_response={},
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_interrupted_scan_resumes_without_repeating_calls(client):
    scan_id = queued_scan(client, signup(client, "resume"))
    ScanService(provider=CountingProvider(), model_registry=ENGINES).run(scan_id)

    # Simulate a worker dying mid-scan: some answers were never stored and the scan is still "running".
    with SessionLocal() as session:
        lost = session.scalars(select(AIResponseRecord.id).where(AIResponseRecord.scan_id == scan_id).limit(3)).all()
        session.execute(delete(AIResponseRecord).where(AIResponseRecord.id.in_(lost)))
        scan = session.get(Scan, scan_id)
        scan.status, scan.completed_at = "running", None
        session.commit()

    provider = CountingProvider()
    ScanService(provider=provider, model_registry=ENGINES).run(scan_id)
    assert sum(provider.calls.values()) == 3  # only the missing answers are fetched again
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        stored = session.scalar(select(func.count()).select_from(AIResponseRecord).where(AIResponseRecord.scan_id == scan_id))
        assert scan.status == "completed" and scan.completed_runs == scan.total_runs == stored


def test_provider_concurrency_is_capped_per_engine(client, monkeypatch):
    monkeypatch.setattr(settings, "scan_concurrency", 8)
    monkeypatch.setattr(settings, "provider_max_parallel_per_engine", 1)
    scan_id = queued_scan(client, signup(client, "cap"))
    provider = CountingProvider(hold=0.01)
    ScanService(provider=provider, model_registry=ENGINES).run(scan_id)
    assert provider.peak["good-model"] == 1 and provider.peak["bad-model"] == 1


def test_daily_scan_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_scans_per_day", 1)
    headers = signup(client, "limit")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    assert client.post(f"{API}/projects/{project_id}/scans", headers=headers).status_code == 200
    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "SCAN_LIMIT_REACHED"


def test_scan_is_sent_to_the_queue_when_redis_is_configured(client, monkeypatch):
    from app.worker.tasks import run_scan_task

    queued: list[int] = []
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(run_scan_task, "delay", lambda scan_id: queued.append(scan_id))
    headers = signup(client, "queue")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)

    started = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert queued == [started["id"]] and started["status"] == "queued"  # API returns before any work happens

    result = run_scan_task.apply(args=[started["id"]])  # what the worker does
    assert result.successful()
    scan = client.get(f"{API}/projects/{project_id}/scans/{started['id']}", headers=headers).json()
    assert scan["status"] == "completed"


def test_unreachable_queue_fails_the_scan_instead_of_hanging(client, monkeypatch):
    from app.worker.tasks import run_scan_task

    def broken(_):
        raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(run_scan_task, "delay", broken)
    headers = signup(client, "noqueue")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)

    response = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    # The project is not stuck: the failed scan no longer blocks a new one.
    monkeypatch.setattr(settings, "redis_url", "")
    assert client.post(f"{API}/projects/{project_id}/scans", headers=headers).status_code == 200
