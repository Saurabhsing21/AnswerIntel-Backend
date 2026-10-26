"""PRD section 97: the 19-step MVP definition, end to end through the API."""

from tests.conftest import API, make_project, signup


def test_mvp_loop_end_to_end(client):
    # 1. Register (and log in)
    headers = signup(client, "mvp")
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200

    # 2-4. Project with website and competitors (limit enforced)
    project_id = make_project(client, headers, (
        ("Kiteline", "https://kiteline.io"), ("Vantor", "https://vantor.app"), ("Norrow", "https://norrow.com"),
    ))
    competitors = client.get(f"{API}/projects/{project_id}/competitors", headers=headers).json()
    assert {c["name"] for c in competitors} == {"Kiteline", "Vantor", "Norrow"}
    duplicate = client.post(f"{API}/projects/{project_id}/competitors", json={"name": "kiteline", "website": "https://k.io"}, headers=headers)
    assert duplicate.status_code == 409

    # 5. Generate prompts
    generated = client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers).json()
    assert generated["created"] >= 20
    prompts = generated["prompts"]
    assert not any(p["text"].lower().startswith("what is halden") for p in prompts)

    # 6. Review prompts: edit one, deactivate one, add one
    first, second = prompts[0], prompts[1]
    edited = client.patch(f"{API}/projects/{project_id}/prompts/{first['id']}", json={"text": "Which CRM should a 10-person startup use?"}, headers=headers)
    assert edited.status_code == 200 and edited.json()["text"].startswith("Which CRM")
    client.patch(f"{API}/projects/{project_id}/prompts/{second['id']}", json={"is_active": False}, headers=headers)
    added = client.post(f"{API}/projects/{project_id}/prompts", json={"text": "Simplest CRM for founder-led sales", "category": "BUYER_INTENT", "intent": "PURCHASE"}, headers=headers)
    assert added.status_code == 200 and added.json()["source"] == "user"
    active = client.get(f"{API}/projects/{project_id}/prompts?status=active", headers=headers).json()
    assert second["id"] not in {p["id"] for p in active}

    # 7-13. Scan: query engines, store raw responses, analyze, detect brand/competitors, extract citations
    started = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert started["status"] == "queued" and started["total_runs"] == len(active) * 3
    scan = client.get(f"{API}/projects/{project_id}/scans/{started['id']}", headers=headers).json()
    assert scan["status"] == "completed" and scan["progress"] == 1 and scan["simulated"] is True

    snapshot_prompts = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/prompts", headers=headers).json()
    assert len(snapshot_prompts) == len(active)
    results = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/results", headers=headers).json()
    assert len(results["prompts"]) == len(active)
    engine_row = results["prompts"][0]["engines"][0]
    assert engine_row["verdict"] in {"recommended", "mentioned", "absent"}
    detail = client.get(f"{API}/projects/{project_id}/responses/{engine_row['response_id']}", headers=headers).json()
    assert detail["text"] and detail["brand"]["name"] == "Halden" and len(detail["competitors"]) == 3

    sources = client.get(f"{API}/projects/{project_id}/citations", headers=headers).json()["sources"]
    assert sources and all(s["source_type"] for s in sources)

    # 14-17. Visibility metrics, dashboard, competitor differences, opportunities
    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert dashboard["has_data"] is True
    v = dashboard["visibility"]
    for key in ("mention_rate", "recommendation_rate", "share_of_voice", "citation_rate"):
        assert 0 <= v[key] <= 1
    assert v["recommendation_rate"] <= v["mention_rate"]
    assert {e["key"] for e in dashboard["engines"]} == {"chatgpt_search", "perplexity", "gemini"}
    assert any(r["is_you"] for r in dashboard["competitors"]) and len(dashboard["competitors"]) == 4
    assert abs(sum(r["share_of_voice"] for r in dashboard["competitors"]) - 1) < 0.01

    analysis = client.get(f"{API}/projects/{project_id}/competitors/analysis", headers=headers).json()
    assert len(analysis["competitors"]) == 3
    opportunities = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    assert opportunities and all(o["evidence"] for o in opportunities)
    moved = client.patch(f"{API}/projects/{project_id}/opportunities/{opportunities[0]['id']}", json={"status": "in_progress"}, headers=headers)
    assert moved.json()["status"] == "in_progress"

    # 18-19. Run another scan and compare results
    client.post(f"{API}/projects/{project_id}/prompts", json={"text": "Best CRM with a free plan for small teams", "category": "BUYER_INTENT", "intent": "PURCHASE"}, headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    dashboard2 = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert len(dashboard2["trend"]) == 2
    assert dashboard2["visibility"]["deltas"]["mention_rate"] is not None
    scans = client.get(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert len(scans) == 2 and all(s["status"] == "completed" for s in scans)
    # History is immutable: the first scan still has its original prompt snapshot.
    first_snapshot = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/prompts", headers=headers).json()
    assert len(first_snapshot) == len(active)

    # Delete cascades through everything.
    assert client.delete(f"{API}/projects/{project_id}", headers=headers).status_code == 200
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).status_code == 404


def test_workspace_isolation(client):
    owner, intruder = signup(client, "owner"), signup(client, "intruder")
    project_id = make_project(client, owner)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=owner)
    scan_id = client.post(f"{API}/projects/{project_id}/scans", headers=owner).json()["id"]
    for path in ("", "/dashboard", "/prompts", "/competitors", "/citations", "/opportunities",
                 f"/scans/{scan_id}", f"/scans/{scan_id}/results", "/competitors/analysis"):
        response = client.get(f"{API}/projects/{project_id}{path}", headers=intruder)
        assert response.status_code == 404, path
    assert client.post(f"{API}/projects/{project_id}/scans", headers=intruder).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/dashboard").status_code == 401


def test_dashboard_before_first_scan(client):
    headers = signup(client, "empty")
    project_id = make_project(client, headers)
    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert dashboard["has_data"] is False and dashboard["latest_scan"] is None
