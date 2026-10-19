"""Answers should match what people see: web search where the consumer app searches, the project's country,
and Google AI Mode through DataForSEO. No network: HTTP calls are replaced."""

import httpx
import pytest

from app.common.config import settings
from app.providers import google_ai
from app.providers.base import ProviderContext
from app.providers.models import GOOGLE_AI_MODEL, configured_engines
from app.providers.openrouter import OpenRouterProvider


class Capture:
    def __init__(self, body: dict):
        self.body, self.calls = body, []

    def __call__(self, url, json=None, **kwargs):
        self.calls.append({"url": url, "json": json, **kwargs})
        return httpx.Response(200, json=self.body, request=httpx.Request("POST", url))


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    capture = Capture({"choices": [{"message": {"content": "Try Halden."}}]})
    monkeypatch.setattr("app.common.llm.httpx.post", capture)
    return capture


def test_engines_that_search_in_their_app_search_here_too(monkeypatch):
    monkeypatch.setattr(settings, "web_search_engines", "chatgpt,gemini")
    monkeypatch.setattr(settings, "dataforseo_login", "")
    engines = {e.key: e.web_search for e in configured_engines()}
    assert engines == {"chatgpt": True, "perplexity": False, "gemini": True}


def test_google_ai_mode_is_added_when_dataforseo_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "me@example.com")
    monkeypatch.setattr(settings, "dataforseo_password", "secret")
    google = [e for e in configured_engines() if e.key == "google"]
    assert len(google) == 1 and google[0].model == GOOGLE_AI_MODEL and google[0].display_name == "Google AI"


def test_web_search_and_country_reach_the_request(openrouter):
    OpenRouterProvider().ask("best crm", "openai/gpt-5.4-nano", ProviderContext(country="India", web_search=True))
    sent = openrouter.calls[0]["json"]
    assert sent["plugins"] == [{"id": "web", "engine": "native"}]
    assert sent["messages"][0] == {"role": "system", "content": "The person asking is located in India."}

    OpenRouterProvider().ask("best crm", "perplexity/sonar", ProviderContext())
    plain = openrouter.calls[1]["json"]
    assert "plugins" not in plain and plain["messages"] == [{"role": "user", "content": "best crm"}]


def test_google_ai_mode_answer_and_sources_are_parsed(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "me@example.com")
    monkeypatch.setattr(settings, "dataforseo_password", "secret")
    body = {"cost": 0.004, "tasks": [{"status_code": 20000, "result": [{"items": [
        {"type": "organic", "url": "https://ignored.example"},
        {"type": "ai_overview", "markdown": "**Halden** is a good pick for startups.", "references": [
            {"url": "https://g2.com/halden", "domain": "g2.com"}, {"url": "https://g2.com/halden", "domain": "g2.com"},
            {"url": "https://halden.co", "domain": "halden.co"}]},
    ]}]}]}
    capture = Capture(body)
    monkeypatch.setattr(google_ai.httpx, "post", capture)

    answer = OpenRouterProvider().ask("best crm", GOOGLE_AI_MODEL, ProviderContext(country="US"))
    assert answer.text == "**Halden** is a good pick for startups." and answer.provider == "dataforseo"
    assert answer.citations == ["https://g2.com/halden", "https://halden.co"]  # deduplicated, in order
    task = capture.calls[0]["json"][0]
    assert task["location_name"] == "United States" and task["language_code"] == "en"
    assert capture.calls[0]["auth"] == ("me@example.com", "secret")


def test_google_ai_mode_without_an_ai_answer_is_an_empty_answer(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "me@example.com")
    monkeypatch.setattr(settings, "dataforseo_password", "secret")
    monkeypatch.setattr(google_ai.httpx, "post", Capture({"tasks": [{"status_code": 20000, "result": [{"items": [{"type": "organic"}]}]}]}))
    answer = OpenRouterProvider().ask("obscure question", GOOGLE_AI_MODEL, ProviderContext())
    assert answer.text == "" and answer.citations == []
