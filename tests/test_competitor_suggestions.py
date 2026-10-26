"""Competitor suggestions for new projects: the model's list is cleaned, and samples are marked when AI is off."""

import json

from app.competitors import suggest
from tests.conftest import API, make_project, signup


def test_samples_are_marked_when_no_ai_key(client):
    headers = signup(client, "suggest")
    project_id = make_project(client, headers)
    result = client.get(f"{API}/projects/{project_id}/competitors/suggestions", headers=headers).json()
    assert result["sample"] is True
    assert "kiteline" not in {s["name"].lower() for s in result["suggestions"]}  # already tracked by make_project


def test_model_suggestions_drop_the_brand_tracked_and_invented_entries(monkeypatch):
    reply = {"competitors": [
        {"name": "Halden", "website": "halden.co", "reason": "itself"},
        {"name": "Kiteline", "website": "https://www.kiteline.io/pricing", "reason": "tracked"},
        {"name": "Pipewise", "website": "www.pipewise.com", "reason": "Same buyers"},
        {"name": "Pipewise", "website": "pipewise.com", "reason": "duplicate"},
        {"name": "Nope", "website": "not a url", "reason": "bad"},
    ]}
    monkeypatch.setattr(suggest.settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(suggest, "chat", lambda *a, **k: {"choices": [{"message": {"content": json.dumps(reply)}}]})
    result = suggest.suggest_competitors("Halden", "https://halden.co", "CRM", "US", None, {"kiteline", "kiteline.io"})
    assert result == {"suggestions": [{"name": "Pipewise", "website": "https://pipewise.com", "reason": "Same buyers"}], "sample": False}


def test_a_failed_model_call_returns_nothing_instead_of_an_error(monkeypatch):
    monkeypatch.setattr(suggest.settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(suggest, "chat", lambda *a, **k: {"choices": [{"message": {"content": "not json"}}]})
    assert suggest.suggest_competitors("Halden", "halden.co", "CRM", "US", None, set()) == {"suggestions": [], "sample": False}


def test_onboarding_suggests_competitors_before_a_project_exists(client):
    headers = signup(client, "onboard")
    body = {"brand_name": " Halden ", "website": "halden.co", "category": "CRM", "country": "United States"}
    result = client.post(f"{API}/onboarding/competitors", json=body, headers=headers).json()
    assert result["sample"] is True and result["suggestions"]
    assert client.get(f"{API}/projects", headers=headers).json() == []  # nothing created yet


def test_site_lookup_reads_name_and_description(client, monkeypatch):
    page = '<html><head><title>Halden | CRM for startups</title><meta name="description" content="The CRM founders set up in 10 minutes."></head></html>'
    monkeypatch.setattr("app.onboarding.router.safe_get", lambda url: (200, page))
    headers = signup(client, "site")
    info = client.get(f"{API}/onboarding/site", params={"url": "halden.co"}, headers=headers).json()
    assert info == {"name": "Halden", "description": "The CRM founders set up in 10 minutes.", "categories": []}
