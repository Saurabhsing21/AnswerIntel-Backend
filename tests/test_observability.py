"""PRD sections 63, 65: request ids, structured logs without secrets, readiness, security headers, safe config."""

import json
import logging

import pytest
from pydantic import ValidationError

from app.common import observability
from app.common.config import Settings, settings
from tests.conftest import API, make_project, signup


def test_every_response_carries_a_request_id(client):
    generated = client.get("/health").headers["x-request-id"]
    assert len(generated) >= 16
    assert client.get("/health").headers["x-request-id"] != generated  # unique per request


def test_a_valid_incoming_request_id_is_kept_and_a_hostile_one_replaced(client):
    assert client.get("/health", headers={"X-Request-ID": "trace-abc_123"}).headers["x-request-id"] == "trace-abc_123"
    for hostile in ("x" * 200, "has spaces", "semi;colon", "<script>"):
        assert client.get("/health", headers={"X-Request-ID": hostile}).headers["x-request-id"] != hostile


def test_access_log_has_timing_and_never_the_query_string_or_credentials(client, caplog):
    headers = signup(client, "logs")
    with caplog.at_level(logging.INFO, logger="answerintel.access"):
        client.get(f"{API}/auth/me?token=super-secret-query", headers=headers)
    record = next(r for r in caplog.records if r.name == "answerintel.access" and r.path.endswith("/auth/me"))
    assert record.method == "GET" and record.status == 200 and record.duration_ms >= 0 and record.request_id
    everything = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "super-secret-query" not in everything and headers["Authorization"] not in everything


def test_json_formatter_emits_one_valid_json_object_with_extras():
    record = logging.LogRecord("answerintel.test", logging.WARNING, __file__, 1, "scan finished", None, None)
    record.scan_id = 7
    line = observability.JsonFormatter().format(record)
    data = json.loads(line)
    assert data["level"] == "WARNING" and data["message"] == "scan finished" and data["scan_id"] == 7 and data["ts"]


def test_security_headers(client, monkeypatch):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in response.headers  # only meaningful over HTTPS in production

    monkeypatch.setattr(settings, "app_env", "production")
    assert "max-age" in client.get("/health").headers["strict-transport-security"]


def test_ready_reports_dependencies(client, monkeypatch):
    ok = client.get("/ready")
    assert ok.status_code == 200 and ok.json()["checks"]["database"] == "ok" and ok.json()["checks"]["redis"] == "skipped"

    def broken():
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(observability, "check_database", broken)
    down = client.get("/ready")
    assert down.status_code == 503 and down.json()["checks"]["database"] == "failed"
    assert "hunter2" not in down.text and "db.internal" not in down.text  # no internals leaked


def test_shared_report_html_is_locked_down_by_csp(client):
    headers = signup(client, "csp")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "weekly"}, headers=headers).json()
    token = client.post(f"{API}/projects/{project_id}/reports/{report['id']}/share", headers=headers).json()["token"]
    csp = client.get(f"{API}/shared/reports/{token}?format=html").headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp and "frame-ancestors 'none'" in csp


@pytest.mark.parametrize("secret", ["short", "change-this-to-a-long-random-secret-value-0000", ""])
def test_production_refuses_weak_jwt_secrets(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql+psycopg://x", jwt_secret_key=secret, app_env="production")


def test_production_accepts_a_strong_secret_and_development_stays_flexible():
    strong = "k9Xv2mQ8rT5wZ1pL7nB4cD6fG3hJ0sA9"
    assert Settings(_env_file=None, database_url="postgresql+psycopg://x", jwt_secret_key=strong, app_env="production", openrouter_api_key="sk-or-x")
    assert Settings(_env_file=None, database_url="postgresql+psycopg://x", jwt_secret_key="dev", app_env="development")


def test_production_needs_an_ai_key_unless_it_only_serves_the_waitlist():
    strong = "k9Xv2mQ8rT5wZ1pL7nB4cD6fG3hJ0sA9"
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None, database_url="postgresql+psycopg://x", jwt_secret_key=strong, app_env="production")
    assert Settings(_env_file=None, database_url="postgresql+psycopg://x", jwt_secret_key=strong, app_env="production", waitlist_only=True)
