"""The free trial: a new account gets one scan of one brand, after confirming its email."""

import re


from app.common.database import SessionLocal
from tests.conftest import API, make_project, signup


def verify(client, outbox, headers):
    email = client.get(f"{API}/auth/me", headers=headers).json()["email"]
    token = re.search(r"token=([A-Za-z0-9._\-]+)", next(m for m in outbox if m["to"] == email)["html"]).group(1)
    client.post(f"{API}/auth/verify-email", json={"token": token})


def billing_of(client, headers):
    workspace = client.get(f"{API}/workspaces", headers=headers).json()[0]["id"]
    return client.get(f"{API}/workspaces/{workspace}/billing", headers=headers).json()


def test_new_accounts_start_on_the_free_trial(client, trial_signups):
    headers = signup(client, "trial")
    billing = billing_of(client, headers)
    assert billing["plan"] == "free" and billing["state"] == "free"
    assert billing["limits"]["scans_total"] == 1 and billing["limits"]["projects"] == 1
    assert billing["usage"]["scans_total"] == 0


def test_one_scan_after_confirming_the_email_then_the_limit(client, outbox, trial_signups):
    headers = signup(client, "trial")
    project_id = make_project(client, headers, competitors=())
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)

    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"

    verify(client, outbox, headers)
    first = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert first.status_code == 200, first.text
    assert billing_of(client, headers)["usage"]["scans_total"] == 1

    with SessionLocal() as session:  # let the in-process scan finish so "already running" doesn't mask the limit
        from app.scans.models import Scan
        session.get(Scan, first.json()["id"]).status = "completed"
        session.commit()
    second = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert second.status_code == 402
    assert second.json()["error"]["limit"] == "scans_total"


def test_the_trial_is_one_project_and_extra_workspaces_get_no_trial(client, trial_signups):
    headers = signup(client, "trial")
    make_project(client, headers, competitors=())
    second = client.post(f"{API}/projects", json={"brand_name": "Other", "website": "https://other.co", "category": "CRM", "country": "US"}, headers=headers)
    assert second.status_code == 402 and second.json()["error"]["limit"] == "projects"

    workspace = client.post(f"{API}/workspaces", json={"name": "Client"}, headers=headers).json()["id"]
    assert client.get(f"{API}/workspaces/{workspace}/billing", headers=headers).json()["state"] == "unsubscribed"


def ready_trial(client, outbox):
    headers = signup(client, "locks")
    verify(client, outbox, headers)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def test_trial_engines_are_capped_at_three_and_premium_ones_are_locked(client, outbox, trial_signups):
    headers, project_id = ready_trial(client, outbox)
    project = client.get(f"{API}/projects/{project_id}", headers=headers).json()
    assert len(project["engines"]) <= 3 and not {"claude", "grok", "google"} & set(project["engines"])

    claude = client.put(f"{API}/projects/{project_id}", json={"engines": ["claude"]}, headers=headers)
    assert claude.status_code == 402 and claude.json()["error"]["limit"] == "engines"
    four = client.put(f"{API}/projects/{project_id}", json={"engines": ["chatgpt", "gemini", "perplexity", "llama"]}, headers=headers)
    assert four.status_code == 402
    assert client.put(f"{API}/projects/{project_id}", json={"engines": ["chatgpt", "llama", "qwen"]}, headers=headers).status_code == 200


def test_paid_features_answer_with_an_upgrade_on_the_trial(client, outbox, trial_signups):
    headers, project_id = ready_trial(client, outbox)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    workspace = client.get(f"{API}/workspaces", headers=headers).json()[0]["id"]
    scan_id = client.get(f"{API}/projects/{project_id}/scans", headers=headers).json()[0]["id"]
    opportunity = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()[0]["id"]
    calls = [
        ("post", f"/projects/{project_id}/prompts/suggest", {"instructions": "pricing"}),
        ("post", f"/projects/{project_id}/prompts", {"text": "Which payroll tool is best for India?"}),
        ("post", f"/projects/{project_id}/opportunities/{opportunity}/draft", None),
        ("post", f"/projects/{project_id}/opportunities/{opportunity}/retest", None),
        ("post", f"/projects/{project_id}/opportunities/{opportunity}/experiment", None),
        ("post", f"/projects/{project_id}/reports", {"type": "manual"}),
        ("get", f"/projects/{project_id}/scans/{scan_id}/export.csv", None),
        ("post", f"/workspaces/{workspace}/members", {"email": "friend@example.com"}),
    ]
    for method, path, body in calls:
        response = getattr(client, method)(f"{API}{path}", headers=headers, **({"json": body} if body else {}))
        assert response.status_code == 402 and response.json()["error"]["limit"] == "pro", path


def test_trial_sees_its_top_three_fixes_and_sources_the_rest_locked(client, outbox, trial_signups):
    headers, project_id = ready_trial(client, outbox)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    opportunities = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    open_rows = [o for o in opportunities if o["trend"] != "resolved"]
    assert all(not o["locked"] for o in open_rows[:3])
    assert all(o["locked"] and not o["steps"] and o["evidence"] == {} for o in open_rows[3:])
    sources = client.get(f"{API}/projects/{project_id}/citations", headers=headers).json()["sources"]
    assert all(not s["locked"] for s in sources[:3]) and all(s["locked"] and s["urls"] == [] for s in sources[3:])
