import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.common.config import settings
from app.common.database import SessionLocal
from app.costs.models import AICall
from app.users.models import User
from app.workspaces.models import WorkspaceMember
from tests.conftest import API, make_project, signup


@pytest.fixture
def admin(client, monkeypatch):
    """A verified account listed in ADMIN_EMAILS, plus its workspace id."""
    headers = signup(client, "boss")
    email = client.get(f"{API}/auth/me", headers=headers).json()["email"]
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        user.email_verified_at = datetime.now(timezone.utc)
        workspace_id = session.scalar(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id))
        session.commit()
    monkeypatch.setattr(settings, "admin_emails", f"someone@else.com, {email.upper()}")
    return headers, workspace_id


@pytest.fixture
def calls():
    """Insert ai_calls rows and remove them afterwards: the test database is shared by every run."""
    ids = []

    def add(workspace_id, cost, purpose, days_ago=0, model="test/m", engine="chatgpt", searches=0):
        with SessionLocal() as session:
            row = AICall(workspace_id=workspace_id, purpose=purpose, provider="openrouter", model=model, engine=engine,
                         cost_usd=Decimal(str(cost)), web_searches=searches, cost_source="provider", status="ok",
                         created_at=datetime.now(timezone.utc).replace(hour=12, minute=0) - timedelta(days=days_ago))
            session.add(row)
            session.commit()
            ids.append(row.id)

    yield add
    with SessionLocal() as session:
        session.execute(delete(AICall).where(AICall.id.in_(ids)))
        session.commit()


def test_access_control(client, admin):
    headers, _ = admin
    assert client.get(f"{API}/admin/costs", headers=headers).status_code == 200
    assert client.get(f"{API}/auth/me", headers=headers).json()["is_admin"] is True

    member = signup(client, "member")
    assert client.get(f"{API}/admin/costs", headers=member).status_code == 404
    assert client.get(f"{API}/auth/me", headers=member).json()["is_admin"] is False
    assert client.get(f"{API}/admin/costs").status_code == 401


def test_unverified_admin_email_is_refused(client, monkeypatch):
    headers = signup(client, "squatter")
    monkeypatch.setattr(settings, "admin_emails", client.get(f"{API}/auth/me", headers=headers).json()["email"])
    assert client.get(f"{API}/admin/costs", headers=headers).status_code == 404


def test_no_admins_configured_means_nobody(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    assert client.get(f"{API}/admin/costs", headers=admin[0]).status_code == 404


def test_numbers_match_inserted_calls(client, admin, calls):
    headers, workspace_id = admin
    purpose = f"admin-test-{uuid.uuid4().hex[:8]}"
    before = client.get(f"{API}/admin/costs?days=7", headers=headers).json()
    calls(workspace_id, 900000.25, purpose, searches=2)
    calls(workspace_id, 0.5, purpose, model="test/other")
    calls(workspace_id, 3, purpose, days_ago=2)
    after = client.get(f"{API}/admin/costs?days=7", headers=headers).json()

    assert len(after["by_day"]) == 7
    day = lambda body, ago: next(d for d in body["by_day"] if d["date"] == (datetime.now(timezone.utc) - timedelta(days=ago)).date().isoformat())
    assert day(after, 2)["cost"] - day(before, 2)["cost"] == pytest.approx(3)
    assert after["range_total"] - before["range_total"] == pytest.approx(900003.75)

    row = next(r for r in after["by_purpose"] if r["key"] == [purpose])
    assert (row["cost"], row["calls"], row["web_searches"]) == (pytest.approx(900003.75), 3, 2)
    models = {tuple(r["key"]): r for r in after["by_model"]}
    assert models[("test/other", "chatgpt")]["cost"] >= 0.5

    top = after["top_workspaces"][0]
    assert top["workspace_id"] == str(workspace_id)
    assert top["spend_this_month"] >= 900000.25 + 0.5
    assert top["cap"] > 0 and top["percent_of_cap"] > 100
    assert len(after["top_workspaces"]) <= 10
    assert after["this_month"] - before["this_month"] >= 900000.75 - 1e-6
    assert after["today"] - before["today"] == pytest.approx(900000.75)


def test_recent_scans_and_margin(client, admin):
    headers, _ = admin
    make_project(client, headers)
    body = client.get(f"{API}/admin/costs", headers=headers).json()
    assert len(body["recent_scans"]) <= 20
    assert all({"cost", "ai_calls", "web_searches", "brand"} <= set(s) for s in body["recent_scans"])
    for row in body["margin_by_plan"]:
        assert row["margin"] == pytest.approx(row["revenue"] - row["ai_spend"])
