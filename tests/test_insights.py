"""Trust and action features: why AI picked a brand, noise-aware numbers, exports, drop alerts, drafts, free check."""

import csv
import io
import uuid

from sqlalchemy import select

from app.common.config import settings
from app.common.database import SessionLocal
from app.metrics.alerts import alert_on_drop
from app.metrics.models import MetricSnapshot
from app.opportunities.models import Opportunity
from app.projects.models import Project
from app.scans.models import Scan
from tests.conftest import API, make_project, signup


def scanned(client, prefix):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    return headers, project_id, scan["id"]


def test_answers_carry_the_sentence_behind_each_verdict(client):
    headers, project_id, scan_id = scanned(client, "evidence")
    responses = client.get(f"{API}/projects/{project_id}/scans/{scan_id}/responses", headers=headers).json()
    details = [client.get(f"{API}/projects/{project_id}/responses/{r['id']}", headers=headers).json() for r in responses[:12]]
    quoted = [d for d in details if d["brand"] and d["brand"]["mentioned"]]
    assert quoted, "the simulated engines should mention the brand somewhere"
    for d in quoted:
        assert d["brand"]["evidence"] and d["brand"]["evidence"] in d["text"]
    for d in details:
        for c in d["competitors"]:
            assert "reason" in c and (c["evidence"] is None or c["evidence"] in d["text"])


def test_dashboard_says_how_much_each_rate_can_move_by_chance(client):
    headers, project_id, _ = scanned(client, "margins")
    visibility = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()["visibility"]
    assert 0 < visibility["margins"]["mention_rate"] < 0.5
    assert visibility["significant"]["mention_rate"] is None  # nothing to compare with yet


def test_scan_exports_as_csv(client):
    headers, project_id, scan_id = scanned(client, "csv")
    response = client.get(f"{API}/projects/{project_id}/scans/{scan_id}/export.csv", headers=headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert f'seenlens-scan-{scan_id}.csv' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    answers = client.get(f"{API}/projects/{project_id}/scans/{scan_id}/responses", headers=headers).json()
    assert rows[0][:3] == ["prompt", "category", "engine"] and len(rows) == len(answers) + 1
    stranger = signup(client, "csvstranger")
    assert client.get(f"{API}/projects/{project_id}/scans/{scan_id}/export.csv", headers=stranger).status_code == 404


def test_a_real_drop_emails_the_owner_and_noise_does_not(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.billing.emails.send_report_email", lambda to, subject, html: sent.append(subject))
    headers = signup(client, "drop")
    project_id = uuid.UUID(make_project(client, headers))

    def scan_with(mention, recommend, n):
        with SessionLocal() as session:
            scan = Scan(project_id=project_id, status="completed", total_runs=n)
            session.add(scan)
            session.flush()
            session.add(MetricSnapshot(project_id=project_id, scan_id=scan.id, total_responses=n, mention_rate=mention,
                                       recommendation_rate=recommend, share_of_voice=0.2, citation_rate=0.1,
                                       positive_sentiment_rate=0.5, average_position=None, by_engine={}))
            session.commit()
            return scan.id

    scan_with(0.80, 0.60, 300)
    noisy = scan_with(0.77, 0.58, 300)  # within noise
    with SessionLocal() as session:
        assert alert_on_drop(session, session.get(Scan, noisy)) is False
    real = scan_with(0.40, 0.20, 300)
    with SessionLocal() as session:
        assert alert_on_drop(session, session.get(Scan, real)) is True
    assert sent == ["AI visibility dropped for Halden"]


def test_opportunity_draft(client):
    headers, project_id, scan_id = scanned(client, "draft")
    with SessionLocal() as session:
        opp = Opportunity(project_id=uuid.UUID(project_id), scan_id=scan_id, type="CONTENT_GAP", title="Publish a comparison page",
                          description="AI never mentions you for comparisons.", recommended_action="Write a Halden vs Kiteline page.",
                          impact="high", confidence=0.8, evidence={"prompts": ["Halden vs Kiteline"]})
        session.add(opp)
        session.commit()
        opp_id = opp.id
    draft = client.post(f"{API}/projects/{project_id}/opportunities/{opp_id}/draft", headers=headers).json()
    assert draft["generated"] is False and draft["markdown"].startswith("# Publish a comparison page")
    assert client.post(f"{API}/projects/{project_id}/opportunities/999999/draft", headers=headers).status_code == 404


def test_free_check_is_off_by_default(client, monkeypatch):
    monkeypatch.setattr(settings, "free_check_enabled", False)
    body = {"brand_name": "Halden", "website": "halden.co", "category": "CRM software"}
    assert client.post(f"{API}/free-check", json=body).status_code == 404


def test_free_check_runs_reuses_and_is_capped(client, monkeypatch):
    monkeypatch.setattr(settings, "free_check_enabled", True)
    monkeypatch.setattr(settings, "free_checks_per_client", 10_000)  # every test run comes from the same address
    site = f"brand-{uuid.uuid4().hex[:8]}.io"
    body = {"brand_name": "Halden", "website": f"https://www.{site}/pricing", "category": "CRM software"}
    started = client.post(f"{API}/free-check", json=body)
    assert started.status_code == 200 and started.json()["website"] == site
    check = client.get(f"{API}/free-check/{started.json()['id']}").json()
    assert check["status"] == "done"
    result = check["result"]
    assert len(result["prompts"]) == settings.free_check_prompts
    assert all("halden" not in p["text"].lower() for p in result["prompts"])  # unbranded questions only
    assert result["summary"]["answers"] == settings.free_check_prompts * 2 and result["simulated"] is True

    assert client.post(f"{API}/free-check", json=body).json()["id"] == started.json()["id"]  # same site today: reused
    assert client.post(f"{API}/free-check", json={**body, "website": "not a site"}).status_code == 422

    monkeypatch.setattr(settings, "free_checks_per_day", 0)
    capped = client.post(f"{API}/free-check", json={**body, "website": f"other-{site}"})
    assert capped.status_code == 429 and capped.json()["error"]["code"] == "FREE_CHECK_LIMIT"


def test_experiment_comparison_flags_noise(client):
    headers, project_id, _ = scanned(client, "expnoise")
    exp = client.post(f"{API}/projects/{project_id}/experiments", json={"name": "FAQ"}, headers=headers).json()
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    done = client.post(f"{API}/projects/{project_id}/experiments/{exp['id']}/complete", headers=headers).json()
    assert set(done["comparison"]["mention_rate"]) == {"before", "after", "delta", "significant"}
    assert done["comparison"]["average_position"]["significant"] is None
