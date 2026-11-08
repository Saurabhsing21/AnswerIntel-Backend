import uuid
from collections import Counter

import httpx
import pytest
from sqlalchemy import func, select

from app.common import llm
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.llm import chat
from app.costs import service as costs
from app.costs.models import AICall
from app.costs.service import cost_scope
from app.projects.models import Project
from app.providers.models import ModelConfig
from app.providers.openrouter import OpenRouterProvider
from app.providers.registry import ModelRegistry
from app.scans.models import Scan
from app.scans.service import ScanService
from tests.conftest import API, make_project, signup

def unique(name: str) -> str:
    return f"test/{name}-{uuid.uuid4().hex[:8]}"


MESSAGES = [{"role": "user", "content": "hi"}]


class FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code, self._body = status_code, body

    def json(self):
        return self._body


def ok_body(cost=0.00123, content="hello", with_usage=True):
    body = {"id": "gen-abc", "choices": [{"message": {"content": content}}]}
    if with_usage:
        body["usage"] = {
            "prompt_tokens": 11, "completion_tokens": 7, "cost": cost,
            "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens_details": {"reasoning_tokens": 2},
        }
    return body


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "provider_max_retries", 2)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def fake_post(monkeypatch, responses):
    sent, queue = [], list(responses)

    def post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm.httpx, "post", post)
    return sent


def rows_for(model: str) -> list[AICall]:
    with SessionLocal() as session:
        return list(session.scalars(select(AICall).where(AICall.model == model).order_by(AICall.id)))


def test_successful_call_writes_exact_cost_row(ai_on, monkeypatch):
    sent = fake_post(monkeypatch, [FakeResponse(200, ok_body())])
    model = unique("success")
    chat(model, MESSAGES, web_search=True)
    assert sent[0]["usage"] == {"include": True}
    (row,) = rows_for(model)
    assert str(row.cost_usd) == "0.001230"
    assert (row.input_tokens, row.output_tokens, row.reasoning_tokens, row.cached_tokens) == (11, 7, 2, 3)
    assert row.generation_id == "gen-abc"
    assert (row.cost_source, row.status, row.provider, row.web_searches, row.purpose) == ("provider", "ok", "openrouter", 1, "other")
    assert row.latency_ms is not None


def test_missing_cost_is_estimated_as_zero(ai_on, monkeypatch):
    fake_post(monkeypatch, [FakeResponse(200, ok_body(with_usage=False))])
    model = unique("nocost")
    chat(model, MESSAGES)
    (row,) = rows_for(model)
    assert row.cost_source == "estimated" and row.cost_usd == 0 and row.status == "ok"


def test_retry_after_500_records_each_attempt(ai_on, monkeypatch):
    fake_post(monkeypatch, [FakeResponse(500, {}), FakeResponse(200, ok_body())])
    model = unique("retry")
    chat(model, MESSAGES)
    assert [r.status for r in rows_for(model)] == ["failed", "ok"]


def test_network_error_records_failed_row_with_zero_cost(ai_on, monkeypatch):
    monkeypatch.setattr(settings, "provider_max_retries", 0)
    fake_post(monkeypatch, [httpx.ConnectError("down")])
    model = unique("net")
    with pytest.raises(llm.LLMError):
        chat(model, MESSAGES)
    (row,) = rows_for(model)
    assert row.status == "failed" and row.cost_usd == 0


def test_cost_scope_nesting():
    with cost_scope(purpose="draft", engine="chatgpt"):
        with cost_scope(purpose="free_check"):
            assert costs._scope.get() == {"purpose": "free_check", "engine": "chatgpt"}
        assert costs._scope.get() == {"purpose": "draft", "engine": "chatgpt"}
    assert costs._scope.get() == {}


def test_db_failure_does_not_break_chat(ai_on, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(costs, "SessionLocal", broken)
    fake_post(monkeypatch, [FakeResponse(200, ok_body())])
    assert chat("test/model-dbfail", MESSAGES)["id"] == "gen-abc"


def test_threaded_scan_rows_carry_scan_attribution(client, ai_on, monkeypatch):
    registry = ModelRegistry([ModelConfig("chatgpt_search", "test/scan-model", "One"), ModelConfig("perplexity", "test/scan-model-2", "Two")])
    def post(url, json=None, headers=None, timeout=None):
        content = '{"brands": []}' if json.get("response_format") else "1. Halden is great."
        return FakeResponse(200, ok_body(content=content))

    monkeypatch.setattr(llm.httpx, "post", post)
    headers = signup(client, "costs")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=registry).start_scan(session, project)
        session.commit()
        scan_id, workspace_id = scan.id, project.workspace_id
    ScanService(provider=OpenRouterProvider(), model_registry=registry).run(scan_id)
    with SessionLocal() as session:
        assert session.get(Scan, scan_id).completed_runs > 0
        rows = list(session.scalars(select(AICall).where(AICall.scan_id == scan_id)))
    assert {r.purpose for r in rows} == {"scan_answer", "answer_analysis"}
    assert {r.engine for r in rows} == {"chatgpt_search", "perplexity"}
    assert all(str(r.project_id) == project_id and r.workspace_id == workspace_id for r in rows)


def test_chat_retries_keyword_overrides_the_setting(ai_on, monkeypatch):
    sent = fake_post(monkeypatch, [FakeResponse(503, {})])
    with pytest.raises(llm.LLMError):
        chat(unique("no-retry"), MESSAGES, retries=0)
    assert len(sent) == 1  # settings.provider_max_retries is 2, but retries=0 wins


def test_scan_answer_is_attempted_once_per_executor_attempt(client, ai_on, monkeypatch):
    """The executor's 30s/2m/10m backoff is the only retry layer for scan answers: 4 attempts, not 4 x 3."""
    registry = ModelRegistry([ModelConfig("chatgpt_search", "test/one-layer", "One")])
    monkeypatch.setattr("app.scans.execution._backoff", lambda s: None)
    posted: list[str] = []

    def post(url, json=None, headers=None, timeout=None):
        posted.append(json["messages"][-1]["content"])
        return FakeResponse(503, {})

    monkeypatch.setattr(llm.httpx, "post", post)
    headers = signup(client, "onelayer")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=registry).start_scan(session, project)
        session.commit()
        scan_id = scan.id
    ScanService(provider=OpenRouterProvider(), model_registry=registry).run(scan_id)
    assert posted and set(Counter(posted).values()) == {len(settings.retry_delays) + 1}


def test_free_check_calls_are_recorded_as_free_check(ai_on, monkeypatch):
    from app.freecheck.models import FreeCheck
    from app.freecheck.service import run_free_check

    def post(url, json=None, headers=None, timeout=None):
        content = '{"brands": []}' if json.get("response_format") else "1. Halden is great."
        return FakeResponse(200, ok_body(content=content))

    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(settings, "free_check_prompts", 1)
    marker = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        check = FreeCheck(brand_name=f"Halden{marker}", website=f"halden{marker}.co", category="CRM software", country="US", client="t", status="queued")
        session.add(check)
        session.commit()
        check_id = check.id
        before = session.scalar(select(func.max(AICall.id))) or 0
    run_free_check(check_id)
    with SessionLocal() as session:
        assert session.get(FreeCheck, check_id).status == "done"
        rows = list(session.scalars(select(AICall).where(AICall.id > before)))
    assert rows and {r.purpose for r in rows} == {"free_check"}


class FakeHttpxResponse:
    def __init__(self, status_code, body=None):
        self.status_code, self._body = status_code, body or {}

    def json(self):
        return self._body


def test_google_ai_success_records_exact_cost(monkeypatch):
    from app.providers import google_ai

    monkeypatch.setattr(settings, "dataforseo_login", "login")
    monkeypatch.setattr(settings, "dataforseo_password", "pw")
    body = {"cost": 0.0042, "tasks": [{"status_code": 20000, "result": [{"items": [
        {"type": "ai_overview", "markdown": "Halden is great.", "references": [{"url": "https://a.example"}]}]}]}]}
    monkeypatch.setattr(google_ai.httpx, "post", lambda *a, **k: FakeHttpxResponse(200, body))
    with SessionLocal() as session:
        before = session.scalar(select(func.max(AICall.id))) or 0
    with cost_scope(purpose="scan_answer", engine="google_ai"):
        google_ai.ask_google_ai("best crm")
    with SessionLocal() as session:
        rows = list(session.scalars(select(AICall).where(AICall.id > before)))
    assert len(rows) == 1
    row = rows[0]
    assert (row.provider, row.model, row.status, row.web_searches) == ("dataforseo", "google-ai-mode", "ok", 1)
    assert (row.purpose, row.engine, row.cost_source) == ("scan_answer", "google_ai", "provider")
    assert float(row.cost_usd) == 0.0042


def test_google_ai_failed_request_records_failed_zero_cost(monkeypatch):
    from app.common.llm import LLMError
    from app.providers import google_ai

    monkeypatch.setattr(settings, "dataforseo_login", "login")
    monkeypatch.setattr(settings, "dataforseo_password", "pw")

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(google_ai.httpx, "post", boom)
    with SessionLocal() as session:
        before = session.scalar(select(func.max(AICall.id))) or 0
    with pytest.raises(LLMError):
        google_ai.ask_google_ai("best crm")
    with SessionLocal() as session:
        rows = list(session.scalars(select(AICall).where(AICall.id > before)))
    assert len(rows) == 1
    assert (rows[0].provider, rows[0].status, rows[0].web_searches, float(rows[0].cost_usd), rows[0].cost_source) == (
        "dataforseo", "failed", 0, 0.0, "estimated")


def test_scan_totals_match_ledger_and_finalize_is_idempotent(client, ai_on, monkeypatch):
    from decimal import Decimal

    from app.costs.service import finalize_scan_cost
    from app.reports.service import create_report

    registry = ModelRegistry([ModelConfig("chatgpt_search", "test/tot-model", "One")])

    def post(url, json=None, headers=None, timeout=None):
        content = '{"brands": []}' if json.get("response_format") else "1. Halden is great."
        return FakeResponse(200, ok_body(content=content))

    monkeypatch.setattr(llm.httpx, "post", post)
    headers = signup(client, "costtotals")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        scan = ScanService(model_registry=registry).start_scan(session, project)
        session.commit()
        scan_id = scan.id
    ScanService(provider=OpenRouterProvider(), model_registry=registry).run(scan_id)
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        total, count, searches = session.execute(
            select(func.sum(AICall.cost_usd), func.count(AICall.id), func.coalesce(func.sum(AICall.web_searches), 0)).where(AICall.scan_id == scan_id)
        ).one()
        assert count > 0 and total > 0
        assert (scan.cost_usd, scan.ai_calls, scan.web_searches) == (total, count, searches)
        finalize_scan_cost(session, scan)
        session.commit()
        session.refresh(scan)
        assert (scan.cost_usd, scan.ai_calls) == (total, count)
        report = create_report(session, session.get(Project, scan.project_id), "manual")
        assert report.scan_id == scan_id and report.cost_usd == scan.cost_usd > Decimal(0)
        assert "cost_usd" not in str(client.get(f"{API}/projects/{project_id}/scans/{scan_id}", headers=headers).json())
