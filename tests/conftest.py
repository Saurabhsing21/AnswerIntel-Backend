import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

API = "/api/v1"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def signup(client: TestClient, prefix: str = "user") -> dict[str, str]:
    email = f"{prefix}-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    token = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_project(client: TestClient, headers: dict, competitors=(("Kiteline", "https://kiteline.io"), ("Vantor", "https://vantor.app"))) -> str:
    project_id = client.post(
        f"{API}/projects",
        json={"brand_name": "Halden", "website": "https://halden.co", "description": "CRM for startups",
              "category": "CRM software", "country": "US"},
        headers=headers,
    ).json()["id"]
    for name, website in competitors:
        client.post(f"{API}/projects/{project_id}/competitors", json={"name": name, "website": website}, headers=headers)
    return project_id
