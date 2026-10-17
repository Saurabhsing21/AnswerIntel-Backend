"""PRD sections 7, 9, 64: workspaces with roles; every project query is scoped to workspace membership."""

import uuid

from tests.conftest import API, make_project, signup

PROJECT = {"brand_name": "Halden", "website": "https://halden.co", "description": "CRM", "category": "CRM software", "country": "US"}


def account(client, prefix):
    email = f"{prefix}-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    token = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


def team(client, headers, name="Growth team") -> str:
    created = client.post(f"{API}/workspaces", json={"name": name}, headers=headers)
    assert created.status_code == 200 and created.json()["role"] == "owner"
    return created.json()["id"]


def test_every_user_gets_a_personal_workspace(client):
    headers = signup(client, "personal")
    workspaces = client.get(f"{API}/workspaces", headers=headers).json()
    assert len(workspaces) == 1 and workspaces[0]["role"] == "owner"

    project = client.post(f"{API}/projects", json=PROJECT, headers=headers).json()
    assert project["workspace_id"] == workspaces[0]["id"]  # lands in the personal workspace by default


def test_members_share_projects_and_strangers_do_not(client):
    _, owner = account(client, "owner")
    member_email, member = account(client, "member")
    _, stranger = account(client, "stranger")
    workspace_id = team(client, owner)

    project = client.post(f"{API}/projects", json={**PROJECT, "workspace_id": workspace_id}, headers=owner).json()
    project_id = project["id"]
    for headers in (member, stranger):
        assert client.get(f"{API}/projects/{project_id}", headers=headers).status_code == 404

    added = client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": member_email}, headers=owner)
    assert added.status_code == 200 and added.json()["role"] == "member"

    assert client.get(f"{API}/projects/{project_id}", headers=member).status_code == 200
    assert project_id in {p["id"] for p in client.get(f"{API}/projects", headers=member).json()}
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=member).status_code == 200
    assert client.get(f"{API}/projects/{project_id}/experiments", headers=member).status_code == 200
    for path in ("", "/dashboard", "/experiments", "/reports", "/schedule", "/competitors"):
        assert client.get(f"{API}/projects/{project_id}{path}", headers=stranger).status_code == 404, path

    removed = client.delete(f"{API}/workspaces/{workspace_id}/members/{added.json()['user_id']}", headers=owner)
    assert removed.status_code == 200
    assert client.get(f"{API}/projects/{project_id}", headers=member).status_code == 404  # access ends at once


def test_cannot_create_a_project_in_someone_elses_workspace(client):
    _, owner = account(client, "wsowner")
    _, other = account(client, "wsother")
    workspace_id = team(client, owner)
    response = client.post(f"{API}/projects", json={**PROJECT, "workspace_id": workspace_id}, headers=other)
    assert response.status_code == 404 and response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"


def test_only_owners_and_admins_manage_members(client):
    _, owner = account(client, "mgr")
    member_email, member = account(client, "plain")
    newbie_email, _ = account(client, "newbie")
    workspace_id = team(client, owner)
    client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": member_email}, headers=owner)

    denied = client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": newbie_email}, headers=member)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    # Members can see who is in the workspace.
    assert len(client.get(f"{API}/workspaces/{workspace_id}/members", headers=member).json()) == 2


def test_admins_cannot_grant_ownership(client):
    _, owner = account(client, "boss")
    admin_email, admin = account(client, "adm")
    target_email, _ = account(client, "target")
    workspace_id = team(client, owner)
    client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": admin_email, "role": "admin"}, headers=owner)

    assert client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": target_email, "role": "owner"}, headers=admin).status_code == 403
    assert client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": target_email, "role": "member"}, headers=admin).status_code == 200


def test_member_edge_cases(client):
    owner_email, owner = account(client, "edge")
    member_email, _ = account(client, "edgem")
    workspace_id = team(client, owner)
    url = f"{API}/workspaces/{workspace_id}/members"

    assert client.post(url, json={"email": f"ghost-{uuid.uuid4().hex}@example.com"}, headers=owner).json()["error"]["code"] == "USER_NOT_FOUND"
    assert client.post(url, json={"email": member_email}, headers=owner).status_code == 200
    assert client.post(url, json={"email": member_email}, headers=owner).status_code == 409  # already a member
    assert client.post(url, json={"email": member_email, "role": "superuser"}, headers=owner).status_code == 422

    me = client.get(f"{API}/auth/me", headers=owner).json()["id"]
    last_owner = client.delete(f"{url}/{me}", headers=owner)
    assert last_owner.status_code == 409 and last_owner.json()["error"]["code"] == "LAST_OWNER"
