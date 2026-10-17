"""PRD sections 41, 42, 54: track a change with a baseline scan and an after scan."""

from tests.conftest import API, make_project, signup


def ready_project(client, prefix="exp"):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def scan(client, headers, project_id):
    started = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    return client.get(f"{API}/projects/{project_id}/scans/{started['id']}", headers=headers).json()


def test_experiment_requires_a_baseline_scan(client):
    headers, project_id = ready_project(client)
    response = client.post(f"{API}/projects/{project_id}/experiments", json={"name": "New pricing page"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_BASELINE_SCAN"


def test_experiment_before_after_comparison(client):
    headers, project_id = ready_project(client)
    baseline_scan = scan(client, headers, project_id)

    created = client.post(
        f"{API}/projects/{project_id}/experiments",
        json={"name": "Startup CRM landing page", "description": "Ship /crm-for-startups"},
        headers=headers,
    )
    assert created.status_code == 200
    experiment = created.json()
    assert experiment["status"] == "running"
    assert experiment["baseline"]["scan_id"] == baseline_scan["id"]
    assert experiment["after"] is None and experiment["comparison"] is None

    # Completing before any newer scan exists has nothing to compare against.
    too_early = client.post(f"{API}/projects/{project_id}/experiments/{experiment['id']}/complete", headers=headers)
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == "NO_FOLLOWUP_SCAN"

    after_scan = scan(client, headers, project_id)
    done = client.post(f"{API}/projects/{project_id}/experiments/{experiment['id']}/complete", headers=headers)
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed" and body["ended_at"] is not None
    assert body["after"]["scan_id"] == after_scan["id"]
    for key in ("mention_rate", "recommendation_rate", "share_of_voice"):
        assert body["comparison"][key]["delta"] == round(body["after"][key] - body["baseline"][key], 4)
    assert "average_position" in body["comparison"]

    # A completed experiment cannot be completed twice.
    again = client.post(f"{API}/projects/{project_id}/experiments/{experiment['id']}/complete", headers=headers)
    assert again.status_code == 409

    fetched = client.get(f"{API}/projects/{project_id}/experiments/{experiment['id']}", headers=headers).json()
    assert fetched == body
    listed = client.get(f"{API}/projects/{project_id}/experiments", headers=headers).json()
    assert [e["id"] for e in listed] == [experiment["id"]]


def test_experiments_are_private_to_their_owner(client):
    headers, project_id = ready_project(client, "owner")
    scan(client, headers, project_id)
    experiment = client.post(f"{API}/projects/{project_id}/experiments", json={"name": "Private"}, headers=headers).json()

    stranger = signup(client, "stranger")
    assert client.get(f"{API}/projects/{project_id}/experiments", headers=stranger).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/experiments/{experiment['id']}", headers=stranger).status_code == 404
    assert client.post(f"{API}/projects/{project_id}/experiments/{experiment['id']}/complete", headers=stranger).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/experiments/{experiment['id'] + 999}", headers=headers).status_code == 404
