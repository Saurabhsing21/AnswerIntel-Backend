import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.common.config import settings
from app.common.database import SessionLocal
from app.costs import service as costs
from app.costs.models import AICall
from app.projects.models import Project
from app.schedules.service import dispatch_due_scans
from tests.conftest import API, make_project, signup
from tests.test_schedules import created_at, enable, next_slot


def workspace_of(project_id):
    with SessionLocal() as session:
        return session.get(Project, uuid.UUID(project_id)).workspace_id


def spend(workspace_id, amount):
    with SessionLocal() as session:
        session.add(AICall(workspace_id=workspace_id, purpose="scan", provider="openrouter", model="m", cost_usd=Decimal(amount),
                           cost_source="provider", status="ok"))
        session.commit()


def project_with_prompts(client, prefix):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def test_global_daily_budget_blocks_user_scans_and_alerts_once(client, monkeypatch, caplog):
    headers, project_id = project_with_prompts(client, "budget")
    spend(workspace_of(project_id), "0.5")  # a known row for today, so spend_today is at least 0.5 whatever else is stored
    monkeypatch.setattr(settings, "daily_ai_budget_usd", 0.5)  # small and positive: reached
    monkeypatch.setattr(costs, "_alerted_on", None)
    with caplog.at_level(logging.ERROR, logger=costs.log.name):
        for _ in range(2):
            res = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
            assert res.status_code == 429
            assert "AI_BUDGET_REACHED" in res.text
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def test_budget_zero_disables_the_global_limit(client, monkeypatch):
    headers, project_id = project_with_prompts(client, "nolimit")
    monkeypatch.setattr(settings, "daily_ai_budget_usd", 0)
    assert client.post(f"{API}/projects/{project_id}/scans", headers=headers).status_code != 429


def test_workspace_cap_blocks_user_scans(client):
    headers, project_id = project_with_prompts(client, "cap")
    spend(workspace_of(project_id), "60")  # test workspaces are on Pro: 50% of $100 = $50 a month
    res = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def test_scheduled_dispatch_skips_a_capped_workspace(client):
    headers, project_id = project_with_prompts(client, "capsched")
    enable(client, headers, project_id, day_of_week=2, hour=10)
    spend(workspace_of(project_id), "60")
    slot = next_slot(created_at(project_id), 2, 10)
    assert dispatch_due_scans(slot, lambda *a: None, project_ids=[uuid.UUID(project_id)]) == []


def test_retest_is_blocked_by_the_workspace_cap(client):
    headers, project_id = project_with_prompts(client, "capretest")
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    for _ in range(60):
        if client.get(f"{API}/projects/{project_id}/scans/{scan['id']}", headers=headers).json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    target = next(o for o in client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json() if o["related_prompts"])
    spend(workspace_of(project_id), "60")
    res = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/retest", headers=headers)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def capped_project(client, prefix):
    headers, project_id = project_with_prompts(client, prefix)
    spend(workspace_of(project_id), "60")
    return headers, project_id


def test_prompt_generation_and_suggestions_are_blocked_by_the_workspace_cap(client):
    headers, project_id = capped_project(client, "capprompts")
    for path, body in (("generate", None), ("suggest", {"instructions": "pricing questions", "count": 3})):
        res = client.post(f"{API}/projects/{project_id}/prompts/{path}", headers=headers, json=body)
        assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def test_competitor_suggestions_are_blocked_by_the_workspace_cap(client):
    headers, project_id = capped_project(client, "capcomp")
    res = client.get(f"{API}/projects/{project_id}/competitors/suggestions", headers=headers)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def test_opportunity_drafts_are_blocked_by_the_workspace_cap(client):
    headers, project_id = project_with_prompts(client, "capdraft")
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    for _ in range(60):
        if client.get(f"{API}/projects/{project_id}/scans/{scan['id']}", headers=headers).json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    target = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()[0]
    spend(workspace_of(project_id), "60")
    res = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/draft", headers=headers)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def test_onboarding_ai_calls_use_the_users_workspace_cap(client, monkeypatch):
    headers, project_id = capped_project(client, "caponboard")
    brand = {"brand_name": "Halden", "website": "https://halden.co", "category": "CRM", "country": "US"}
    res = client.post(f"{API}/onboarding/competitors", headers=headers, json=brand)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    page = "<title>Halden</title><meta name='description' content='CRM for startups'>"
    monkeypatch.setattr("app.onboarding.router.safe_get", lambda url: (200, page))
    res = client.get(f"{API}/onboarding/site", params={"url": "halden.co"}, headers=headers)
    assert res.status_code == 402 and "WORKSPACE_COST_CAP" in res.text


def test_onboarding_without_a_workspace_is_only_held_by_the_global_budget(client, monkeypatch):
    from app.workspaces.models import WorkspaceMember

    headers = signup(client, "nows")
    with SessionLocal() as session:
        session.query(WorkspaceMember).filter(WorkspaceMember.user_id == client.get(f"{API}/auth/me", headers=headers).json()["id"]).delete()
        session.commit()
    spend(None, "0.5")
    monkeypatch.setattr(settings, "daily_ai_budget_usd", 0.5)
    brand = {"brand_name": "Halden", "website": "https://halden.co", "category": "CRM", "country": "US"}
    res = client.post(f"{API}/onboarding/competitors", headers=headers, json=brand)
    assert res.status_code == 429 and "AI_BUDGET_REACHED" in res.text


def test_free_check_is_blocked_by_the_global_budget(client, monkeypatch):
    monkeypatch.setattr(settings, "free_check_enabled", True)
    spend(None, "0.5")
    monkeypatch.setattr(settings, "daily_ai_budget_usd", 0.5)
    body = {"brand_name": "Halden", "website": f"nobudget-{uuid.uuid4().hex[:8]}.example.com", "category": "CRM software"}
    res = client.post(f"{API}/free-check", json=body)
    assert res.status_code == 429 and "AI_BUDGET_REACHED" in res.text


def test_workspace_lock_key_is_stable_and_distinct_per_workspace():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert costs.workspace_lock_key(a) == costs.workspace_lock_key(uuid.UUID(str(a)))
    assert costs.workspace_lock_key(a) != costs.workspace_lock_key(b)
    assert -(2**63) <= costs.workspace_lock_key(a) < 2**63


def test_concurrent_starts_for_a_one_scan_workspace_create_exactly_one_scan(client, trial_signups, outbox):
    """Check + insert run under the workspace lock, so the second start sees the first scan instead of racing past the limit."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import func, select

    from app.common.errors import AppError
    from app.scans.models import Scan
    from app.scans.service import ScanService
    from tests.test_free_trial import verify

    headers = signup(client, "race")
    verify(client, outbox, headers)  # the free plan allows one scan in total
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    barrier = Barrier(2)

    def start(_):
        with SessionLocal() as session:
            project = session.get(Project, uuid.UUID(project_id))
            barrier.wait(timeout=10)
            try:
                costs.check_budget(session, project.workspace_id, lock=True)
                ScanService().start_scan(session, project)
                session.commit()
                return "started"
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(pool.map(start, range(2)))
    assert outcomes[1] == "started" and outcomes[0] in ("PLAN_LIMIT", "SCAN_ALREADY_RUNNING", "SCAN_LIMIT_REACHED")
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Scan).where(Scan.project_id == uuid.UUID(project_id))) == 1
