"""The action loop: opportunities keep their status across scans, show what changed, and a fix can be re-tested."""

from app.metrics.service import Observation
from app.opportunities.service import detect
from app.scans.models import Scan
from app.common.database import SessionLocal
from tests.conftest import API, make_project, signup


def scan_and_wait(client, headers, project_id):
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    with SessionLocal() as s:  # in tests the scan runs in-process before the response returns
        assert s.get(Scan, scan["id"]).status in ("completed", "partial")
    return scan


def opportunities(client, headers, project_id):
    return client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()


def test_status_and_trend_carry_across_scans(client):
    headers = signup(client, "loop")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    first = opportunities(client, headers, project_id)
    assert first and all(o["trend"] == "new" and o["steps"] and o["effort"] in "SML" for o in first)

    dismissed, working = first[0], first[-1]
    client.patch(f"{API}/projects/{project_id}/opportunities/{dismissed['id']}", json={"status": "dismissed"}, headers=headers)
    client.patch(f"{API}/projects/{project_id}/opportunities/{working['id']}", json={"status": "in_progress"}, headers=headers)

    scan_and_wait(client, headers, project_id)
    by_type = {}
    for o in opportunities(client, headers, project_id):
        by_type.setdefault((o["type"], o["evidence"].get("competitor") or o["evidence"].get("category")), o)
    kept = by_type[(dismissed["type"], dismissed["evidence"].get("competitor") or dismissed["evidence"].get("category"))]
    assert kept["status"] == "dismissed" and kept["trend"] != "new"
    assert kept["first_seen_scan_id"] == dismissed["scan_id"]


def test_a_gap_that_disappears_is_reported_as_resolved(client):
    from app.opportunities import service

    headers = signup(client, "resolved")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    before = opportunities(client, headers, project_id)

    real = service.detect
    try:
        service.detect = lambda *a, **k: real(*a, **k)[1:]  # the top gap is fixed by the next scan
        scan_and_wait(client, headers, project_id)
    finally:
        service.detect = real
    after = opportunities(client, headers, project_id)
    resolved = [o for o in after if o["trend"] == "resolved"]
    assert [o["title"] for o in resolved] == [before[0]["title"]] and resolved[0]["status"] == "completed"


def test_retest_asks_only_that_opportunitys_prompts_and_reports_before_and_after(client):
    headers = signup(client, "retest")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    full = scan_and_wait(client, headers, project_id)
    target = next(o for o in opportunities(client, headers, project_id) if o["related_prompts"])

    started = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/retest", headers=headers).json()
    assert started["status"] == "completed" and started["retest"]["before"]["scan_id"] == full["id"]
    done = client.get(f"{API}/projects/{project_id}/opportunities/{target['id']}", headers=headers).json()["retest"]
    assert done["status"] == "done" and done["after"]["answers"] > 0
    assert done["after"]["answers"] <= done["before"]["answers"]  # only this opportunity's prompts were asked

    scans = client.get(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert scans[0]["kind"] == "retest" and scans[0]["total_runs"] < scans[1]["total_runs"]
    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert dashboard["latest_scan"]["id"] == full["id"]  # a re-test never becomes the dashboard's scan


def test_track_as_experiment_freezes_a_baseline_once(client):
    headers = signup(client, "track")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    target = opportunities(client, headers, project_id)[0]
    tracked = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/experiment", headers=headers).json()
    assert tracked["status"] == "in_progress" and tracked["experiment_id"]
    again = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/experiment", headers=headers).json()
    assert again["experiment_id"] == tracked["experiment_id"]
    experiments = client.get(f"{API}/projects/{project_id}/experiments", headers=headers).json()
    assert [e["name"] for e in experiments] == [f"Fix: {target['title']}"]


def test_competitor_steps_name_the_page_and_the_domains_behind_the_answer():
    def obs(i, mentioned, comp_rec, domains):
        return Observation(
            response_id=i, engine="chatgpt", scan_prompt_id=i, prompt_id=i, prompt_text=f"best crm {i}", category="CATEGORY",
            brand={"mentioned": mentioned, "recommended": False, "position": None, "sentiment": None},
            competitors={7: {"mentioned": True, "recommended": comp_rec, "position": 1, "sentiment": "positive"}},
            citations=[{"domain": d, "is_brand_owned": False, "competitor_id": None} for d in domains],
        )
    found = detect([obs(i, False, True, ["g2.com", "zapier.com"]) for i in range(3)], "Halden", {7: "Kiteline"})
    gap = next(f for f in found if f["type"] == "COMPETITOR_GAP")
    steps = " ".join(gap["evidence"]["steps"])
    assert "/halden-vs-kiteline" in steps and "g2.com" in steps and gap["evidence"]["effort"] == "M"


def test_first_scan_sends_a_ready_email_once(client, outbox):
    headers = signup(client, "ready")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    scan_and_wait(client, headers, project_id)
    assert [m["subject"] for m in outbox if "is ready" in m["subject"]] == ["Your first scan of Halden is ready"]


def test_overtake_lists_questions_a_competitor_took_from_you(client, outbox, monkeypatch):
    from app.metrics import alerts

    headers = signup(client, "overtake")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    monkeypatch.setattr(alerts, "overtakes", lambda session, scan: [("best crm for startups", "Kiteline")])
    scan_and_wait(client, headers, project_id)
    mail = next(m for m in outbox if m["subject"] == "A competitor overtook Halden")
    assert "Kiteline on &quot;best crm for startups&quot;" in mail["html"]


def test_free_follow_ups_go_out_once_each_in_order(client, outbox, trial_signups):
    from datetime import datetime, timedelta, timezone

    from app.billing.emails import send_free_nudges

    headers = signup(client, "nudge")
    email = client.get(f"{API}/auth/me", headers=headers).json()["email"]
    now = datetime.now(timezone.utc)
    subjects = lambda: [m["subject"] for m in outbox if m["to"] == email and "Confirm" not in m["subject"]]  # noqa: E731
    send_free_nudges(now)
    assert subjects() == []  # too early
    send_free_nudges(now + timedelta(days=1, minutes=1))
    send_free_nudges(now + timedelta(days=1, minutes=2))
    assert subjects() == ["Your free AI visibility scan is waiting"]
    send_free_nudges(now + timedelta(days=8))
    send_free_nudges(now + timedelta(days=9))
    send_free_nudges(now + timedelta(days=10))
    assert len(subjects()) == 3


def test_dashboard_has_this_weeks_plan_and_splits_named_from_category_questions(client):
    headers = signup(client, "week")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    week = dashboard["this_week"]
    assert 1 <= len(week["items"]) <= 3 and week["done"] == 0
    first = week["items"][0]
    client.patch(f"{API}/projects/{project_id}/opportunities/{first['id']}", json={"status": "completed"}, headers=headers)
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()["this_week"]["done"] == 1

    split = dashboard["visibility"]["by_question"]
    assert split["category"]["responses"] > 0 and split["named"]["responses"] > 0
    assert split["category"]["responses"] + split["named"]["responses"] == dashboard["visibility"]["total_responses"]
