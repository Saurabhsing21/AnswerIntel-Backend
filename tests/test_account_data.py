"""Data export and account deletion."""

import json
import uuid

from sqlalchemy import select

from app.auth import google
from app.billing import paddle_client
from app.billing.models import Subscription
from app.common import storage
from app.common.database import SessionLocal
from app.costs.models import AICall
from app.projects.models import Project
from app.reports.models import Report, ReportPdf
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember
from tests.conftest import API
from tests.test_reports import ready_project, run_scan


def me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()


def scanned_account(client, prefix="exp"):
    headers, project_id = ready_project(client, prefix)
    run_scan(client, headers, project_id)
    client.post(f"{API}/projects/{project_id}/reports", json={"type": "manual"}, headers=headers)
    return headers, project_id


def delete(client, headers, **body):
    return client.request("DELETE", f"{API}/auth/me", json=body, headers=headers)


def test_export_has_the_users_data_but_no_raw_provider_json_or_costs(client):
    headers, project_id = scanned_account(client)
    response = client.get(f"{API}/auth/me/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="seenlense-export-')
    data = response.json()
    assert data["account"]["email"] == me(client, headers)["email"]
    project = data["workspaces"][0]["projects"][0]
    assert project["id"] == project_id and project["brand_name"] == "Halden"
    assert project["questions"] and {c["name"] for c in project["competitors"]} == {"Kiteline", "Vantor"}
    answer = project["scans"][0]["answers"][0]
    assert answer["answer"] and answer["question"] and answer["engine"]
    assert any(a["brand"] is not None for s in project["scans"] for a in s["answers"])
    assert any(a["competitors"] for s in project["scans"] for a in s["answers"])
    assert project["reports"] and project["reports"][0]["content"]["brand"] == "Halden"
    text = json.dumps(data).lower()
    assert "raw_response" not in text and "cost" not in text and "latency" not in text


def test_export_only_includes_workspaces_the_user_owns(client):
    headers, _ = scanned_account(client, "expown")
    other, other_project = scanned_account(client, "expother")
    email = me(client, headers)["email"]
    workspace_id = client.get(f"{API}/workspaces", headers=other).json()[0]["id"]
    client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": email, "role": "member"}, headers=other)
    ids = [p["id"] for w in client.get(f"{API}/auth/me/export", headers=headers).json()["workspaces"] for p in w["projects"]]
    assert other_project not in ids


def test_delete_needs_the_right_password_and_removes_everything(client, monkeypatch):
    headers, project_id = scanned_account(client, "del")
    user_id = me(client, headers)["id"]
    email = me(client, headers)["email"]
    with SessionLocal() as session:
        workspace_id = session.scalar(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id))
        call = AICall(workspace_id=workspace_id, project_id=project_id, user_id=user_id, purpose="scan", provider="p", model="m",
                      cost_usd=1, cost_source="provider", status="ok")
        session.add(call)
        session.commit()
        call_id = call.id
    assert delete(client, headers, password="wrong-password").status_code == 400
    assert delete(client, headers).status_code == 400
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200

    assert delete(client, headers, password="password123").json() == {"ok": True}
    with SessionLocal() as session:
        assert session.get(User, user_id) is None
        assert session.get(Workspace, workspace_id) is None
        assert session.get(Project, project_id) is None
        kept = session.get(AICall, call_id)  # the cost ledger keeps its rows, detached from the deleted account
        assert kept is not None and kept.user_id is None and kept.workspace_id is None
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": email, "password": "password123"}).status_code == 401


def test_delete_cancels_paddle_and_removes_r2_files(client, monkeypatch):
    headers, project_id = scanned_account(client, "delr2")
    user_id = me(client, headers)["id"]
    canceled, removed = [], []
    sub_id = f"sub_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(paddle_client, "cancel_subscription", canceled.append)
    monkeypatch.setattr(storage, "delete", removed.append)
    with SessionLocal() as session:
        workspace_id = session.scalar(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id))
        session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id)).paddle_subscription_id = sub_id
        report_id = session.scalar(select(ReportPdf.report_id).join(Report, Report.id == ReportPdf.report_id).where(Report.project_id == project_id))
        session.get(ReportPdf, report_id).storage_key = f"reports/{project_id}/{report_id}.pdf"
        session.commit()
    assert delete(client, headers, password="password123").status_code == 200
    assert canceled == [sub_id] and removed == [f"reports/{project_id}/{report_id}.pdf"]


def test_paddle_failure_leaves_the_account_untouched(client, monkeypatch):
    headers, _ = scanned_account(client, "delfail")
    user_id = me(client, headers)["id"]
    from app.common.errors import AppError

    def boom(_):
        raise AppError(502, "BILLING_PROVIDER_ERROR", "down")

    monkeypatch.setattr(paddle_client, "cancel_subscription", boom)
    sub_id = f"sub_{uuid.uuid4().hex[:10]}"
    with SessionLocal() as session:
        wid = session.scalar(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id))
        session.scalar(select(Subscription).where(Subscription.workspace_id == wid)).paddle_subscription_id = sub_id
        session.commit()
    assert delete(client, headers, password="password123").status_code == 502
    with SessionLocal() as session:
        assert session.get(User, user_id) is not None


def test_sole_owner_of_a_workspace_with_members_gets_409(client):
    headers, project_id = scanned_account(client, "del409")
    other, _ = scanned_account(client, "del409b")
    workspace_id = client.get(f"{API}/workspaces", headers=headers).json()[0]["id"]
    other_email = me(client, other)["email"]
    assert client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": other_email, "role": "member"}, headers=headers).status_code == 200
    response = delete(client, headers, password="password123")
    assert response.status_code == 409 and response.json()["error"]["code"] == "WORKSPACE_HAS_MEMBERS"
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200

    # Once someone else is an owner, leaving is fine and the workspace and its project stay with them.
    other_id = me(client, other)["id"]
    client.patch(f"{API}/workspaces/{workspace_id}/members/{other_id}", json={"role": "owner"}, headers=headers)
    assert delete(client, headers, password="password123").status_code == 200
    with SessionLocal() as session:
        assert session.get(Workspace, uuid.UUID(workspace_id)) is not None
        assert session.get(Project, project_id).user_id == other_id
    assert client.get(f"{API}/projects/{project_id}", headers=other).status_code == 200


def test_google_only_account_confirms_with_a_fresh_google_token(client, monkeypatch):
    headers, _ = scanned_account(client, "delg")
    email = me(client, headers)["email"]
    monkeypatch.setattr(google, "verified_email", lambda credential: {"good": email, "other": "someone@else.com"}.get(credential))
    assert delete(client, headers, google_credential="other").status_code == 400
    assert delete(client, headers, google_credential="bad").status_code == 400
    assert delete(client, headers, google_credential="good").status_code == 200
