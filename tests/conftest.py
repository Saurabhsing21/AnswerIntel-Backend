import uuid

import pytest
from fastapi.testclient import TestClient

from app.common.config import settings
from app.main import app

API = "/api/v1"


@pytest.fixture(autouse=True)
def rate_limits_off(monkeypatch):
    """Tests sign up and log in from one address; the limits have their own tests in test_rate_limits.py."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


@pytest.fixture(autouse=True)
def no_network_site_audit(monkeypatch):
    """Scans audit the brand's website; tests must never reach the real internet."""
    monkeypatch.setattr("app.opportunities.site_audit.safe_get", lambda url, **kwargs: None)


@pytest.fixture(autouse=True)
def no_backoff_waiting(monkeypatch):
    """Provider retries use the real 30s/2m/10m delays in production; tests must not sleep through them."""
    monkeypatch.setattr("app.scans.execution._backoff", lambda seconds: None)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def signup(client: TestClient, prefix: str = "user") -> dict[str, str]:
    email = f"{prefix}-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    token = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_project(client: TestClient, headers: dict, competitors=(("Kiteline", "https://kiteline.io"), ("Vantor", "https://vantor.app"))) -> str:
    project_id = client.post(
        f"{API}/projects",
        json={"brand_name": "Halden", "website": "https://halden.co", "description": "CRM for startups",
              "category": "CRM software", "country": "US"},
        headers=headers,
    ).json()["id"]
    for name, website in competitors:
        client.post(f"{API}/projects/{project_id}/competitors", json={"name": name, "website": website}, headers=headers)
    return project_id
