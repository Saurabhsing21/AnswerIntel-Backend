"""Answers should match what people see: web search where the consumer app searches, the project's country,
and Google AI Mode through DataForSEO. No network: HTTP calls are replaced."""

import httpx
import pytest

from app.common.config import settings
from app.providers import google_ai
from app.providers.base import ProviderContext
from app.providers.models import GOOGLE_AI_MODEL, engines_for_project
from app.providers.openrouter import OpenRouterProvider
from tests.conftest import API, make_project, signup


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


def test_new_projects_scan_the_default_engines_with_web_search(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "")
    engines = {e.key: e.web_search for e in engines_for_project(None)}
    assert engines == {"chatgpt_search": True, "gemini": True, "perplexity": False}  # Google AI Mode needs DataForSEO


def test_google_ai_mode_is_available_when_dataforseo_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "me@example.com")
    monkeypatch.setattr(settings, "dataforseo_password", "secret")
    google = [e for e in engines_for_project(["google", "claude"]) if e.key == "google"]
    assert len(google) == 1 and google[0].model == GOOGLE_AI_MODEL and google[0].display_name == "Google AI Mode"


def test_engine_models_can_be_swapped_from_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "engine_models", "llama=meta-llama/llama-4-scout")
    assert [e.model for e in engines_for_project(["llama"])] == ["meta-llama/llama-4-scout"]


def test_projects_choose_their_engines_and_scans_use_only_those(client):
    headers = signup(client, "engines")
    catalog = client.get(f"{API}/engines", headers=headers).json()
    assert {"chatgpt", "claude", "grok", "llama", "mistral", "deepseek", "qwen", "copilot"} <= {e["key"] for e in catalog}
    assert next(e for e in catalog if e["key"] == "copilot")["available"] is False
    assert next(e for e in catalog if e["key"] == "claude")["available"] is False  # paused for now

    project_id = make_project(client, headers)
    assert client.put(f"{API}/projects/{project_id}", json={"engines": ["copilot"]}, headers=headers).status_code == 422
    assert client.put(f"{API}/projects/{project_id}", json={"engines": []}, headers=headers).status_code == 422
    updated = client.put(f"{API}/projects/{project_id}", json={"engines": ["llama", "chatgpt", "llama"]}, headers=headers).json()
    assert updated["engines"] == ["chatgpt", "llama"]

    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    answers = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/responses", headers=headers).json()
    assert {a["engine"] for a in answers} == {"chatgpt", "llama"}


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


def test_a_prompt_can_run_on_fewer_engines_than_the_project(client):
    headers = signup(client, "prompt-engines")
    project_id = make_project(client, headers)
    client.put(f"{API}/projects/{project_id}", json={"engines": ["chatgpt", "llama", "grok"]}, headers=headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    prompts = [p for p in client.get(f"{API}/projects/{project_id}/prompts", headers=headers).json() if p["is_active"]]
    assert all(p["engines"] is None for p in prompts)

    narrowed = client.patch(f"{API}/projects/{project_id}/prompts/{prompts[0]['id']}", json={"engines": ["grok", "llama"]}, headers=headers).json()
    assert narrowed["engines"] == ["grok", "llama"]
    assert client.patch(f"{API}/projects/{project_id}/prompts/{prompts[0]['id']}", json={"engines": ["copilot"]}, headers=headers).status_code == 422

    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert scan["total_runs"] == (len(prompts) - 1) * 3 + 2
    answers = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/responses", headers=headers).json()
    first = [a for a in answers if a["prompt"] == prompts[0]["text"]]
    assert {a["engine"] for a in first} == {"grok", "llama"}

    reset = client.patch(f"{API}/projects/{project_id}/prompts/{prompts[0]['id']}", json={"engines": []}, headers=headers).json()
    assert reset["engines"] is None  # back to every project engine


def test_generate_more_previews_prompts_from_instructions_then_adds_only_the_kept_ones(client):
    headers = signup(client, "suggest-prompts")
    project_id = make_project(client, headers)
    before = len(client.get(f"{API}/projects/{project_id}/prompts", headers=headers).json())

    preview = client.post(f"{API}/projects/{project_id}/prompts/suggest", json={"instructions": "marketing agencies", "count": 4}, headers=headers).json()
    assert preview["sample"] is True and preview["prompts"]  # no AI key in tests: clearly marked stand-ins
    assert all("marketing agencies" in p["text"] for p in preview["prompts"])
    assert len(client.get(f"{API}/projects/{project_id}/prompts", headers=headers).json()) == before  # nothing saved yet

    kept = preview["prompts"][:2]
    added = client.post(f"{API}/projects/{project_id}/prompts/accept", json={"prompts": kept}, headers=headers).json()
    assert added["created"] == 2
    again = client.post(f"{API}/projects/{project_id}/prompts/accept", json={"prompts": kept}, headers=headers).json()
    assert again["created"] == 0  # duplicates are skipped

    repeat = client.post(f"{API}/projects/{project_id}/prompts/suggest", json={"instructions": "marketing agencies", "count": 4}, headers=headers).json()
    assert {p["text"] for p in repeat["prompts"]}.isdisjoint({p["text"] for p in kept})  # never suggests what exists


def test_instructions_reach_the_model_as_marked_user_input(monkeypatch):
    from app.prompts import generator

    seen = {}

    def fake(model, system, user, schema):
        seen["user"] = user
        return schema(prompts=[{"text": "Which CRM suits a 5-person agency?", "category": "USE_CASE", "intent": "DISCOVERY"}])

    monkeypatch.setattr(generator, "complete_json", fake)
    data = generator.PromptInput("Halden", "CRM", "US", None, ["Kiteline"], instructions="small agencies")
    out = generator.LLMPromptGenerator(count=5).generate(data)
    assert "<user_request>\nsmall agencies\n</user_request>" in seen["user"] and "Generate 5 new prompts" in seen["user"]
    assert out[0]["text"] == "Which CRM suits a 5-person agency?"


def test_a_refused_request_fails_at_once_instead_of_retrying(monkeypatch):
    """An unverified DataForSEO account or a bad key answers 4xx forever; the scan must not wait out the backoff."""
    import httpx
    from app.common.llm import PermanentLLMError
    from app.providers import google_ai

    monkeypatch.setattr(settings, "dataforseo_login", "x")
    monkeypatch.setattr(settings, "dataforseo_password", "y")
    calls = []
    monkeypatch.setattr(google_ai.httpx, "post", lambda *a, **k: calls.append(1) or httpx.Response(403, json={}))
    with pytest.raises(PermanentLLMError):
        google_ai.ask_google_ai("best SIP app")
    assert len(calls) == 1


def test_gemini_redirect_citations_name_the_real_site():
    from app.providers.openrouter import extract_citations

    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ"
    data = {"choices": [{"message": {"annotations": [
        {"type": "url_citation", "url_citation": {"url": redirect + "a", "title": "kuvera.in"}},
        {"type": "url_citation", "url_citation": {"url": redirect + "b", "title": "icici.bank.in"}},
        {"type": "url_citation", "url_citation": {"url": "https://groww.in/mf", "title": "Groww MF"}},
    ]}}]}
    assert extract_citations(data) == ["https://kuvera.in", "https://icici.bank.in", "https://groww.in/mf"]
