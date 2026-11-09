import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.common.config import settings
from app.common.database import SessionLocal
from app.billing.models import Subscription
from app.costs.models import AICall
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember
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
    assert after["range_total"] - before["range_total"] == pytest.approx(900003.75, abs=1e-6)

    row = next(r for r in after["by_purpose"] if r["key"] == [purpose])
    assert (row["cost"], row["calls"], row["web_searches"]) == (pytest.approx(900003.75, abs=1e-6), 3, 2)
    models = {tuple(r["key"]): r for r in after["by_model"]}
    assert models[("test/other", "chatgpt")]["cost"] >= 0.5

    top = after["top_workspaces"][0]
    assert top["workspace_id"] == str(workspace_id)
    assert top["spend_this_month"] >= 900000.25 + 0.5
    assert top["cap"] > 0 and top["percent_of_cap"] > 100
    assert len(after["top_workspaces"]) <= 10
    assert after["this_month"] - before["this_month"] >= 900000.75 - 1e-6
    assert after["today"] - before["today"] == pytest.approx(900000.75, abs=1e-6)


def test_recent_scans_and_margin(client, admin):
    headers, _ = admin
    make_project(client, headers)
    body = client.get(f"{API}/admin/costs", headers=headers).json()
    assert len(body["recent_scans"]) <= 20
    assert all({"cost", "ai_calls", "web_searches", "brand"} <= set(s) for s in body["recent_scans"])


def test_margin_by_plan_exact(client, admin, calls):
    """Seed workspaces on known subscriptions; compare against the report from before, since the shared DB has other rows."""
    headers, _ = admin
    plan_row = lambda body, plan: next((r for r in body["margin_by_plan"] if r["plan"] == plan), dict(active_workspaces=0, revenue=0, ai_spend=0, margin=0))
    before = client.get(f"{API}/admin/costs", headers=headers).json()

    cases = [("starter", "active", "month", 7), ("growth", "active", "year", 11), ("pro", "canceled", "month", 13), (None, None, None, 17)]
    ids = []
    try:
        with SessionLocal() as session:
            for plan, status, interval, _spend in cases:
                workspace = Workspace(name=f"margin-{uuid.uuid4().hex[:6]}")
                session.add(workspace)
                session.flush()
                ids.append(workspace.id)
                if plan:
                    session.add(Subscription(workspace_id=workspace.id, plan=plan, status=status, interval=interval))
            session.commit()
        for workspace_id, (_, _, _, spend) in zip(ids, cases):
            calls(workspace_id, spend, "margin-test")
        after = client.get(f"{API}/admin/costs", headers=headers).json()

        def delta(plan, field):
            return plan_row(after, plan)[field] - plan_row(before, plan)[field]

        # monthly Starter: 20 revenue, 7 spend
        assert (delta("starter", "active_workspaces"), delta("starter", "revenue"), delta("starter", "ai_spend"), delta("starter", "margin")) == (1, pytest.approx(20), pytest.approx(7), pytest.approx(13))
        # yearly Growth: 480 / 12 = 40 revenue, 11 spend
        assert (delta("growth", "active_workspaces"), delta("growth", "revenue"), delta("growth", "ai_spend"), delta("growth", "margin")) == (1, pytest.approx(40), pytest.approx(11), pytest.approx(29))
        # canceled Pro: no revenue, not counted, but its spend still costs us
        assert (delta("pro", "active_workspaces"), delta("pro", "revenue"), delta("pro", "ai_spend"), delta("pro", "margin")) == (0, pytest.approx(0), pytest.approx(13), pytest.approx(-13))
        # no subscription at all: spend only
        assert (delta("none", "active_workspaces"), delta("none", "revenue"), delta("none", "ai_spend"), delta("none", "margin")) == (0, pytest.approx(0), pytest.approx(17), pytest.approx(-17))
    finally:
        # ai_calls.workspace_id is SET NULL on delete; the `calls` fixture removes those rows afterwards by id.
        with SessionLocal() as session:
            session.execute(delete(Workspace).where(Workspace.id.in_(ids)))
            session.commit()


def test_run_detail_shows_real_cost_breakdown(client, admin):
    """A run's drill-down: the scan's stored cost, a per-purpose/engine breakdown, and the billed calls."""
    import uuid as _uuid
    from decimal import Decimal
    from app.projects.models import Project
    from app.scans.models import Scan

    headers, workspace_id = admin
    project_id = make_project(client, headers)
    scan_id = None
    call_ids = []
    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == _uuid.UUID(project_id)))
        scan = Scan(project_id=project.id, status="completed", kind="full", total_runs=2, completed_runs=2,
                    failed_runs=0, credits=Decimal("1.5"), cost_usd=Decimal("0.02"), ai_calls=3, web_searches=1)
        session.add(scan)
        session.flush()
        scan_id = scan.id
        for cost, purpose, engine, searches in [("0.012", "scan_answer", "chatgpt_search", 1),
                                                ("0.006", "scan_answer", "perplexity", 0),
                                                ("0.002", "answer_analysis", "chatgpt_search", 0)]:
            c = AICall(workspace_id=workspace_id, project_id=project.id, scan_id=scan_id, purpose=purpose,
                       provider="openrouter", model="test/m", engine=engine, cost_usd=Decimal(cost),
                       web_searches=searches, cost_source="provider", status="ok")
            session.add(c)
            session.flush()
            call_ids.append(c.id)
        session.commit()

    try:
        r = client.get(f"{API}/admin/runs/{scan_id}", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["scan"]["cost"] == 0.02
        assert body["scan"]["credits_charged"] == 1.5
        assert body["scan"]["cost_per_credit"] == round(0.02 / 1.5, 5)
        assert len(body["breakdown"]) == 3  # two engines on scan_answer + one on answer_analysis
        assert len(body["calls"]) == 3
        assert body["calls"][0]["cost"] == 0.012  # ordered by cost, dearest first
        assert client.get(f"{API}/admin/runs/{scan_id}").status_code == 401  # unauthenticated
        assert client.get(f"{API}/admin/runs/99999999", headers=headers).status_code == 404
    finally:
        with SessionLocal() as session:
            session.execute(delete(AICall).where(AICall.id.in_(call_ids)))
            session.execute(delete(Scan).where(Scan.id == scan_id))
            session.commit()
