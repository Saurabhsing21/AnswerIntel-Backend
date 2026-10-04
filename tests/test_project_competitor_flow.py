import uuid

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

API = "/api/v1"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_project_and_competitor_lifecycle():
    email = f"e2e-{uuid.uuid4().hex}@example.com"
    password = "password123"

    register = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 200, register.text
    assert register.json()["email"] == email

    login = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    create_payload = {
        "brand_name": "AnswerIntel",
        "website": "https://answerintel.example",
        "description": "Track AI answers",
        "category": "SaaS",
        "country": "US",
    }
    created = client.post(f"{API}/projects", json=create_payload, headers=headers)
    assert created.status_code == 200, created.text
    project = created.json()
    project_id = project["id"]
    uuid.UUID(project_id)
    assert project["brand_name"] == "AnswerIntel"
    assert project["website"] == "https://answerintel.example/"
    assert project["category"] == "SaaS"
    assert project["country"] == "US"

    fetched = client.get(f"{API}/projects/{project_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == project_id
    assert fetched.json()["brand_name"] == "AnswerIntel"

    listed = client.get(f"{API}/projects", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == project_id for item in listed.json())

    updated = client.put(
        f"{API}/projects/{project_id}",
        json={"brand_name": "AnswerIntel Updated", "country": "IN"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["brand_name"] == "AnswerIntel Updated"
    assert updated.json()["country"] == "IN"
    assert updated.json()["category"] == "SaaS"

    competitor_payload = {
        "name": "Competitor Co",
        "website": "https://competitor.example",
    }
    added = client.post(
        f"{API}/projects/{project_id}/competitors",
        json=competitor_payload,
        headers=headers,
    )
    assert added.status_code == 200, added.text
    competitor = added.json()
    competitor_id = competitor["id"]
    assert competitor["name"] == "Competitor Co"
    assert competitor["website"] == "https://competitor.example/"

    competitors = client.get(
        f"{API}/projects/{project_id}/competitors",
        headers=headers,
    )
    assert competitors.status_code == 200, competitors.text
    assert any(item["id"] == competitor_id for item in competitors.json())

    deleted_competitor = client.delete(
        f"{API}/projects/{project_id}/competitors/{competitor_id}",
        headers=headers,
    )
    assert deleted_competitor.status_code == 200, deleted_competitor.text
    assert deleted_competitor.json()["message"] == "Competitor deleted successfully"

    remaining = client.get(
        f"{API}/projects/{project_id}/competitors",
        headers=headers,
    )
    assert remaining.status_code == 200, remaining.text
    assert remaining.json() == []

    deleted_project = client.delete(
        f"{API}/projects/{project_id}",
        headers=headers,
    )
    assert deleted_project.status_code == 200, deleted_project.text
    assert deleted_project.json()["message"] == "Project deleted successfully"

    missing = client.get(f"{API}/projects/{project_id}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Project not found"
