import os
import uuid

# Tests write throwaway rows: never let them reach the real (Neon) database from .env.local.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5434/seenlens_test")
os.environ["DATABASE_URL_UNPOOLED"] = ""
assert "neon.tech" not in os.environ["DATABASE_URL"], "TEST_DATABASE_URL must not point at Neon"

import pytest
from fastapi.testclient import TestClient

from app.common.config import settings
from app.main import app
from app.providers.registry import get_provider as real_get_provider

API = "/api/v1"


@pytest.fixture(autouse=True)
def rate_limits_off(monkeypatch):
    """Tests sign up and log in from one address; the limits have their own tests in test_rate_limits.py."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


@pytest.fixture(autouse=True)
def daily_budget_off(monkeypatch):
    """The test database keeps every ai_calls row ever written; the daily budgets have their own tests in test_spend_guardrails.py."""
    monkeypatch.setattr(settings, "daily_ai_budget_usd", 0)
    monkeypatch.setattr(settings, "free_check_daily_budget_usd", 0)


@pytest.fixture(autouse=True)
def no_real_ai_keys(monkeypatch):
    """Keys in a developer's .env must never be used by tests: real AI calls cost money."""
    for key in ("openrouter_api_key", "dataforseo_login", "dataforseo_password", "resend_api_key", "cashfree_client_id", "cashfree_client_secret"):
        monkeypatch.setattr(settings, key, "")


@pytest.fixture(autouse=True)
def simulated_ai(monkeypatch):
    """Production has no path to made-up answers; tests install the simulated engines and template prompts explicitly.
    Tests that exercise the "AI unavailable" paths use the `ai_down` fixture to undo this."""
    from app.prompts.generator import InstructedTemplateGenerator, PromptGenerator, TemplatePromptGenerator
    from tests.simulated_provider import SimulatedAIProvider

    class TemplatePrompts(PromptGenerator):
        def __init__(self, count: int = 40):
            pass

        def generate(self, data):
            return (InstructedTemplateGenerator() if data.instructions else TemplatePromptGenerator()).generate(data)

    for target in ("app.scans.execution.get_provider", "app.freecheck.service.get_provider"):
        monkeypatch.setattr(target, SimulatedAIProvider)
    monkeypatch.setattr("app.prompts.service.LLMPromptGenerator", TemplatePrompts)


@pytest.fixture
def ai_down(monkeypatch):
    """The real wiring with no OpenRouter key: every AI feature must answer 503 AI_UNAVAILABLE."""
    from app.prompts.generator import LLMPromptGenerator

    monkeypatch.setattr("app.prompts.service.LLMPromptGenerator", LLMPromptGenerator)
    for target in ("app.scans.execution.get_provider", "app.freecheck.service.get_provider"):
        monkeypatch.setattr(target, real_get_provider)


@pytest.fixture(autouse=True)
def r2_off(monkeypatch):
    """Real bucket credentials in a developer's .env must never be used by tests; R2 tests fake the S3 client."""
    for key in ("r2_account_id", "r2_bucket", "r2_access_key_id", "r2_secret_access_key"):
        monkeypatch.setattr(settings, key, "")


@pytest.fixture(autouse=True)
def no_network_site_audit(monkeypatch):
    """Scans audit the brand's website; tests must never reach the real internet."""
    monkeypatch.setattr("app.opportunities.site_audit.safe_get", lambda url, **kwargs: None)
    monkeypatch.setattr("app.diagnosis.service.safe_get", lambda url, **kwargs: None)
    monkeypatch.setattr("app.onboarding.router.safe_get", lambda url, **kwargs: None)
    monkeypatch.setattr("app.logos.router.fetch_logo", lambda domain: (None, ""))


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Every email (account, billing, alerts) lands here instead of going out through Resend."""
    sent: list[dict] = []
    capture = lambda to, subject, html: sent.append({"to": to, "subject": subject, "html": html})  # noqa: E731
    monkeypatch.setattr("app.auth.links.send_report_email", capture)
    monkeypatch.setattr("app.billing.emails.send_report_email", capture)  # billing, alerts, "scan ready", free follow-ups
    return sent


@pytest.fixture(autouse=True)
def stub_pdf_renderer(monkeypatch):
    """The Node renderer is exercised in test_report_pdf.py; elsewhere a PDF only needs to exist."""
    monkeypatch.setattr("app.reports.pdf_jobs.render_pdf_bytes", lambda document: b"%PDF-1.7 stub")


@pytest.fixture(autouse=True)
def no_backoff_waiting(monkeypatch):
    """Provider retries use the real 30s/2m/10m delays in production; tests must not sleep through them."""
    monkeypatch.setattr("app.scans.execution._backoff", lambda seconds: None)


@pytest.fixture(autouse=True)
def paid_workspaces(monkeypatch):
    """Every workspace a test creates starts on paid Pro (as if Checkout ran).
    Billing tests that need an unpaid workspace undo this with the `unpaid_signups` fixture."""
    from app.billing import service
    from app.billing.models import Subscription

    real = service.open_billing
    monkeypatch.setattr(service, "open_billing", lambda session, workspace_id, trial=False: session.add(
        Subscription(workspace_id=workspace_id, plan="pro", interval="month", status="active")
    ))
    return real


@pytest.fixture
def unpaid_signups(monkeypatch, paid_workspaces):
    """New workspaces with no plan at all (not even the free trial)."""
    from app.billing import service

    monkeypatch.setattr(service, "open_billing", lambda session, workspace_id, trial=False: paid_workspaces(session, workspace_id))


@pytest.fixture
def trial_signups(monkeypatch, paid_workspaces):
    """New accounts start on the free trial, as in production."""
    from app.billing import service

    monkeypatch.setattr(service, "open_billing", paid_workspaces)


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
