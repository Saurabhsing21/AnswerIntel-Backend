"""PRD sections 10, 37, 39, 53: entity and technical gaps, evidence-shaped recommendations, SSRF-safe site audit."""

import pytest

from app.common import safe_http
from app.metrics.service import Observation
from app.opportunities import site_audit
from app.opportunities.service import AREAS, detect
from tests.conftest import API, make_project, signup


def obs(i, category, mentioned, recommended=False, text=None):
    return Observation(
        response_id=i, engine="chatgpt", scan_prompt_id=i, prompt_id=i, prompt_text=text or f"{category} prompt {i}",
        category=category,
        brand={"mentioned": mentioned, "recommended": recommended, "position": None, "sentiment": "neutral" if mentioned else None},
        competitors={}, citations=[],
    )


# ---- entity gap -----------------------------------------------------------------------------------------------

def test_entity_gap_when_known_by_name_but_not_by_category():
    observations = (
        [obs(i, "CATEGORY", False) for i in range(5)]
        + [obs(10 + i, "USE_CASE", False) for i in range(3)]
        + [obs(20 + i, "COMPARISON", True) for i in range(4)]
    )
    found = {o["type"]: o for o in detect(observations, "Halden", {})}
    gap = found["ENTITY_GAP"]
    assert gap["evidence"]["discovery_rate"] == 0.0 and gap["evidence"]["branded_rate"] == 1.0
    assert gap["evidence"]["prompts"]


def test_no_entity_gap_when_visibility_is_consistent():
    observations = [obs(i, "CATEGORY", i % 2 == 0) for i in range(6)] + [obs(10 + i, "COMPARISON", i % 2 == 0) for i in range(6)]
    assert "ENTITY_GAP" not in {o["type"] for o in detect(observations, "Halden", {})}


def test_every_opportunity_carries_prd_39_fields_and_an_area():
    observations = [obs(i, "CATEGORY", False) for i in range(4)] + [obs(10 + i, "COMPARISON", True) for i in range(4)]
    found = detect(observations, "Halden", {})
    assert found
    for item in found:
        assert item["evidence"]["expected_objective"]
        assert item["type"] in AREAS


# ---- SSRF guard -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fc00::1"])
def test_private_addresses_are_refused(address):
    assert safe_http.is_public_address(address) is False


def test_public_addresses_are_allowed():
    assert safe_http.is_public_address("93.184.216.34") is True


@pytest.mark.parametrize("url", ["ftp://example.com/", "file:///etc/passwd", "http://user:pw@example.com/", "http://example.com:22/", "http:///nohost", "javascript:alert(1)"])
def test_unsafe_urls_are_refused(url):
    with pytest.raises(safe_http.UnsafeURL):
        safe_http.validate_url(url)


def test_hostnames_that_resolve_to_private_addresses_are_refused(monkeypatch):
    monkeypatch.setattr(safe_http.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 80))])
    with pytest.raises(safe_http.UnsafeURL):
        safe_http.validate_url("http://innocent-looking.example.com/")
    # One private answer among public ones is enough to refuse (DNS rebinding tricks).
    monkeypatch.setattr(safe_http.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("127.0.0.1", 80))])
    with pytest.raises(safe_http.UnsafeURL):
        safe_http.validate_url("http://mixed.example.com/")


# ---- technical gap / site audit -------------------------------------------------------------------------------

GOOD_HTML = "<html><head><script type='application/ld+json'>{}</script></head><body>" + "<p>CRM for startups. </p>" * 40 + "</body></html>"


def fake_site(robots="User-agent: *\nAllow: /", llms=True, html=GOOD_HTML):
    def fetch(url):
        if url.endswith("/robots.txt"):
            return 200, robots
        if url.endswith("/llms.txt"):
            return (200, "# Halden") if llms else (404, "")
        return 200, html

    return fetch


def test_healthy_site_has_no_findings():
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site())
    assert audit["findings"] == []


def test_blocked_search_crawlers_are_a_high_impact_finding():
    robots = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /\n\nUser-agent: *\nAllow: /"
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(robots=robots))
    blocked = next(f for f in audit["findings"] if f["code"] == "ROBOTS_BLOCKS_AI")
    assert blocked["impact"] == "high" and set(blocked["agents"]) == {"OAI-SearchBot", "PerplexityBot"}


def test_blocking_only_training_crawlers_is_a_low_impact_note_and_no_gap():
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: CCBot\nDisallow: /\n\nUser-agent: ClaudeBot\nDisallow: /"
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(robots=robots))
    assert [f["code"] for f in audit["findings"]] == ["ROBOTS_BLOCKS_TRAINING"]
    note = audit["findings"][0]
    assert note["impact"] == "low" and "does not hide you from ChatGPT Search" in note["message"]
    assert set(note["agents"]) == {"GPTBot", "CCBot", "ClaudeBot"}
    assert "TECHNICAL_GAP" not in {o["type"] for o in detect([obs(1, "CATEGORY", True)], "Halden", {}, audit=audit)}


def test_missing_llms_txt_is_a_low_tip_and_never_a_gap_on_its_own():
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(llms=False))
    assert [(f["code"], f["impact"]) for f in audit["findings"]] == [("NO_LLMS_TXT", "low")]
    assert "TECHNICAL_GAP" not in {o["type"] for o in detect([obs(1, "CATEGORY", True)], "Halden", {}, audit=audit)}


def test_tips_ride_along_in_the_gap_evidence_when_a_real_finding_exists():
    robots = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /"
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(robots=robots, llms=False))
    gap = next(o for o in detect([obs(1, "CATEGORY", True)], "Halden", {}, audit=audit) if o["type"] == "TECHNICAL_GAP")
    assert gap["impact"] == "high" and gap["title"] == "Your robots.txt blocks AI crawlers"
    assert [f["code"] for f in gap["evidence"]["findings"]] == ["ROBOTS_BLOCKS_AI", "ROBOTS_BLOCKS_TRAINING", "NO_LLMS_TXT"]
    assert all({"code", "impact", "message", "action"} <= set(f) for f in gap["evidence"]["findings"])


def test_missing_llms_structured_data_and_thin_content_are_reported():
    thin = "<html><body><div id='root'></div><script>app()</script></body></html>"
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(llms=False, html=thin))
    assert {f["code"] for f in audit["findings"]} == {"NO_LLMS_TXT", "NO_STRUCTURED_DATA", "THIN_CONTENT"}


def test_unreachable_site_is_not_reported_as_a_technical_gap():
    assert site_audit.audit_site("https://halden.co", fetch=lambda url: None) is None


def test_technical_gap_opportunity_comes_from_audit_findings():
    robots = "User-agent: OAI-SearchBot\nDisallow: /"
    audit = site_audit.audit_site("https://halden.co", fetch=fake_site(robots=robots))
    found = {o["type"]: o for o in detect([obs(1, "CATEGORY", True)], "Halden", {}, audit=audit)}
    gap = found["TECHNICAL_GAP"]
    assert gap["impact"] == "high" and gap["evidence"]["findings"] and "robots.txt" in gap["recommended_action"].lower()
    assert "TECHNICAL_GAP" not in {o["type"] for o in detect([obs(1, "CATEGORY", True)], "Halden", {}, audit=None)}


def test_scan_adds_technical_gap_and_detail_endpoint(client, monkeypatch):
    robots = "User-agent: OAI-SearchBot\nDisallow: /"
    monkeypatch.setattr(site_audit, "safe_get", lambda url, **kw: fake_site(robots=robots)(url))
    headers = signup(client, "tech")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)

    listed = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    technical = next(o for o in listed if o["type"] == "TECHNICAL_GAP")
    assert technical["area"] == "technical" and technical["expected_objective"] and isinstance(technical["related_prompts"], list)

    detail = client.get(f"{API}/projects/{project_id}/opportunities/{technical['id']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["id"] == technical["id"]
    stranger = signup(client, "techstranger")
    assert client.get(f"{API}/projects/{project_id}/opportunities/{technical['id']}", headers=stranger).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/opportunities/99999999", headers=headers).status_code == 404
