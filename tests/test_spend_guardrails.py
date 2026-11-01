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
