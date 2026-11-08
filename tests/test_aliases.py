"""Other names for the brand and competitors: limits, storage, and use in scans and diagnosis."""

import pytest
from sqlalchemy import select

from app.analysis.models import CompetitorObservation, Mention
from app.common.database import SessionLocal
from app.diagnosis.service import diagnose
from app.projects.models import Project
from app.providers.base import AIProvider, AIResponse
from app.providers.models import ModelConfig
from app.providers.registry import ModelRegistry
from app.providers.response_model import AIResponseRecord
from app.scans.service import ScanService
from tests.conftest import API, make_project, signup

ONE_ENGINE = ModelRegistry([ModelConfig("chatgpt_search", "good-model", "Good")])


def new_project(client, headers, **extra) -> str:
    body = {"brand_name": "Halden", "website": "https://halden.co", "category": "CRM software", "country": "US", **extra}
    created = client.post(f"{API}/projects", json=body, headers=headers)
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_project_aliases_default_empty_and_round_trip(client):
    headers = signup(client, "alias")
    project_id = new_project(client, headers)
    assert client.get(f"{API}/projects/{project_id}", headers=headers).json()["aliases"] == []

    updated = client.put(f"{API}/projects/{project_id}", json={"aliases": ["  Halden CRM ", "", "Halden App", "halden crm"]}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["aliases"] == ["Halden CRM", "Halden App"]  # trimmed, blanks and repeats dropped
    assert client.get(f"{API}/projects/{project_id}", headers=headers).json()["aliases"] == ["Halden CRM", "Halden App"]
    assert any(p["aliases"] == ["Halden CRM", "Halden App"] for p in client.get(f"{API}/projects", headers=headers).json())

    # Leaving aliases out of an update keeps them; an empty list clears them.
    assert client.put(f"{API}/projects/{project_id}", json={"country": "IN"}, headers=headers).json()["aliases"] == ["Halden CRM", "Halden App"]
    assert client.put(f"{API}/projects/{project_id}", json={"aliases": []}, headers=headers).json()["aliases"] == []


def test_project_alias_limits(client):
    headers = signup(client, "alias")
    assert new_project(client, headers, aliases=["a", "b", "c", "d", "e"])  # five is the maximum
    too_many = client.post(f"{API}/projects", json={
        "brand_name": "Halden", "website": "https://halden.co", "category": "CRM", "country": "US", "aliases": list("abcdef"),
    }, headers=headers)
    assert too_many.status_code == 422
    project_id = new_project(client, headers, aliases=["x" * 60])  # 60 characters is allowed
    too_long = client.put(f"{API}/projects/{project_id}", json={"aliases": ["x" * 61]}, headers=headers)
    assert too_long.status_code == 422


def test_competitor_aliases_round_trip_and_limits(client):
    headers = signup(client, "alias")
    project_id = new_project(client, headers)
    url = f"{API}/projects/{project_id}/competitors"

    added = client.post(url, json={"name": "HubSpot", "website": "https://hubspot.com", "aliases": ["HubSpot CRM"]}, headers=headers)
    assert added.status_code == 200, added.text
    assert added.json()["aliases"] == ["HubSpot CRM"]
    plain = client.post(url, json={"name": "Attio", "website": "https://attio.com"}, headers=headers)
    assert plain.json()["aliases"] == []
    assert {c["name"]: c["aliases"] for c in client.get(url, headers=headers).json()} == {"HubSpot": ["HubSpot CRM"], "Attio": []}

    competitor_id = added.json()["id"]
    edited = client.patch(f"{url}/{competitor_id}", json={"aliases": ["HubSpot CRM", "Hub Spot"]}, headers=headers)
    assert edited.json()["aliases"] == ["HubSpot CRM", "Hub Spot"]
    assert client.patch(f"{url}/{competitor_id}", json={"website": "https://hubspot.com"}, headers=headers).json()["aliases"] == ["HubSpot CRM", "Hub Spot"]

    assert client.patch(f"{url}/{competitor_id}", json={"aliases": list("abcdef")}, headers=headers).status_code == 422
    assert client.patch(f"{url}/{competitor_id}", json={"aliases": ["x" * 61]}, headers=headers).status_code == 422
    too_many = client.post(url, json={"name": "Zoho", "website": "https://zoho.com", "aliases": list("abcdef")}, headers=headers)
    assert too_many.status_code == 422


class AliasOnlyProvider(AIProvider):
    """Answers with the other names only: the plain names "Halden" and "Kiteline" never appear."""

    @property
    def name(self) -> str:
        return "alias-only"

    def ask(self, prompt, model, context=None):
        return AIResponse(self.name, model, prompt, "1. Halden CRM: simple to start.\n2. Kiteline Pro: strong reporting.", {"ok": True})


def test_scan_uses_the_other_names(client):
    headers = signup(client, "alias")
    project_id = make_project(client, headers)
    client.put(f"{API}/projects/{project_id}", json={"aliases": ["Halden CRM"]}, headers=headers)
    competitors = client.get(f"{API}/projects/{project_id}/competitors", headers=headers).json()
    kiteline = next(c for c in competitors if c["name"] == "Kiteline")
    client.patch(f"{API}/projects/{project_id}/competitors/{kiteline['id']}", json={"aliases": ["Kiteline Pro"]}, headers=headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)

    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id))
        service = ScanService(provider=AliasOnlyProvider(), model_registry=ONE_ENGINE)
        scan = service.start_scan(session, project)
        session.commit()
        scan_id = scan.id
    service.run(scan_id)

    with SessionLocal() as session:
        ids = session.scalars(select(AIResponseRecord.id).where(AIResponseRecord.scan_id == scan_id)).all()
        assert ids
        mentions = session.scalars(select(Mention).where(Mention.ai_response_id.in_(ids))).all()
        assert mentions and all(m.mentioned and m.position == 1 for m in mentions)
        observed: dict[int, set[bool]] = {}
        for o in session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id.in_(ids))):
            observed.setdefault(o.competitor_id, set()).add(o.mentioned)
        assert observed[kiteline["id"]] == {True}
        assert [flags for cid, flags in observed.items() if cid != kiteline["id"]] == [{False}]  # Vantor is named nowhere


def fake_fetch(pages):
    return lambda url: (200, pages[url]) if url in pages else None


def test_diagnosis_source_gap_counts_the_other_names():
    cites = [{"url": "https://g2.com/a", "domain": "g2.com"}, {"url": "https://g2.com/b", "domain": "g2.com"}]
    pages = {
        "https://g2.com/a": "<p>Top picks: Kiteline Pro and Halden CRM.</p>",  # names the brand by its other name: no gap
        "https://g2.com/b": "<p>Top picks: Kiteline Pro.</p>",
    }
    result = diagnose(
        brand="Halden", brand_aliases=["Halden CRM"], website="https://halden.co", engine="perplexity", prompt="best crm",
        mention={"mentioned": False, "recommended": False},
        competitors=[{"name": "Kiteline", "aliases": ["Kiteline Pro"], "recommended": True}],
        citations=cites, fetch=fake_fetch(pages),
    )
    gap = next(c for c in result["causes"] if c["code"] == "SOURCE_GAP")
    assert [p["url"] for p in gap["evidence"]["pages"]] == ["https://g2.com/b"]
    assert gap["evidence"]["pages"][0]["competitors"] == ["Kiteline"]  # reported under the tracked name
