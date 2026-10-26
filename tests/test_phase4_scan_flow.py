import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.prompts.generator import VALID_CATEGORIES
from app.providers.models import V1_MODELS


client = TestClient(app)

API = "/api/v1"
REQUIRED_CATEGORIES = {
    "CATEGORY",
    "ALTERNATIVE",
    "USE_CASE",
    "PROBLEM",
    "BUYER_INTENT",
    "COMPARISON",
    "COMPETITOR",
}
COMPETITORS = [
    ("Notion", "https://notion.so"),
    ("ClickUp", "https://clickup.com"),
    ("Asana", "https://asana.com"),
]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_phase4_scan_flow_with_simulated_provider():
    email = f"phase4-{uuid.uuid4().hex}@example.com"
    password = "password123"

    register = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 200, register.text

    login = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    created_project = client.post(
        f"{API}/projects",
        json={
            "brand_name": "Acme",
            "website": "https://example.com",
            "description": "A productivity platform for startups",
            "category": "productivity software",
            "country": "India",
        },
        headers=headers,
    )
    assert created_project.status_code == 200, created_project.text
    project_id = created_project.json()["id"]
    uuid.UUID(project_id)

    for name, website in COMPETITORS:
        added = client.post(
            f"{API}/projects/{project_id}/competitors",
            json={"name": name, "website": website},
            headers=headers,
        )
        assert added.status_code == 200, added.text

    generated = client.post(
        f"{API}/projects/{project_id}/prompts/generate",
        headers=headers,
    )
    assert generated.status_code == 200, generated.text

    started = client.post(
        f"{API}/projects/{project_id}/scans",
        headers=headers,
    )
    assert started.status_code == 200, started.text
    scan = started.json()
    scan_id = scan["id"]
    assert scan["project_id"] == project_id
    assert scan["status"] == "queued"

    # The TestClient runs background tasks before returning, so the scan is done.
    finished = client.get(f"{API}/projects/{project_id}/scans/{scan_id}", headers=headers).json()
    assert finished["status"] == "completed"
    assert finished["completed_runs"] == finished["total_runs"] > 0

    prompts = client.get(
        f"{API}/projects/{project_id}/scans/{scan_id}/prompts",
        headers=headers,
    )
    assert prompts.status_code == 200, prompts.text
    prompt_rows = prompts.json()
    assert 30 <= len(prompt_rows) <= 50

    categories = {row["category"] for row in prompt_rows}
    assert REQUIRED_CATEGORIES.issubset(categories)
    assert categories.issubset(VALID_CATEGORIES)

    prompt_texts = {row["text"] for row in prompt_rows}
    for name, _website in COMPETITORS:
        assert f"Acme vs {name}: which is better?" in prompt_texts

    prompt_ids = {row["id"] for row in prompt_rows}
    assert all(row["scan_id"] == scan_id for row in prompt_rows)

    responses = client.get(
        f"{API}/projects/{project_id}/scans/{scan_id}/responses",
        headers=headers,
    )
    assert responses.status_code == 200, responses.text
    response_rows = responses.json()

    assert len(response_rows) == len(prompt_rows) * len(V1_MODELS)
    assert {row["model"] for row in response_rows} == {model.model for model in V1_MODELS}

    required_fields = {
        "scan_id",
        "scan_prompt_id",
        "provider",
        "model",
        "prompt",
        "response_text",
        "raw_response",
        "created_at",
    }
    for row in response_rows:
        assert required_fields.issubset(row.keys())
        assert row["scan_id"] == scan_id
        assert row["scan_prompt_id"] in prompt_ids
        assert row["provider"] == "simulated"
        assert row["response_text"]
        assert row["raw_response"]["simulated"] is True
        assert row["created_at"]
