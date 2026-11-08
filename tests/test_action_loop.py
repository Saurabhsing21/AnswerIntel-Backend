"""The action loop: opportunities keep their status across scans, show what changed, and a fix can be re-tested."""

from app.metrics.service import Observation
from app.opportunities.service import detect
from app.providers.response_model import AIResponseRecord
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


def test_a_gap_that_disappears_twice_is_reported_as_resolved(client):
    from app.opportunities import service

    headers = signup(client, "resolved")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    real, first = service.detect, []
    try:
        # Simulated answers vary between scans, so later scans replay the first one's gaps minus the top one.
        service.detect = lambda *a, **k: first.extend(real(*a, **k)) or list(first)
        scan_and_wait(client, headers, project_id)
        service.detect = lambda *a, **k: [dict(x, evidence=dict(x["evidence"])) for x in first[1:]]
        scan_and_wait(client, headers, project_id)
        once = opportunities(client, headers, project_id)
        scan_and_wait(client, headers, project_id)
    finally:
        service.detect = real
    # Missing from one scan is not proof of a fix: it is improving, and keeps its status.
    assert [(o["title"], o["status"]) for o in once if o["trend"] in ("improving", "resolved")] == [(first[0]["title"], "open")]
    assert next(o for o in once if o["title"] == first[0]["title"])["trend"] == "improving"
    after = opportunities(client, headers, project_id)
    resolved = [o for o in after if o["trend"] == "resolved"]
    assert [o["title"] for o in resolved] == [first[0]["title"]] and resolved[0]["status"] == "completed"


def test_old_format_fingerprints_rebaseline_instead_of_reporting_everything_fixed(client):
    from sqlalchemy import select, update

    from app.opportunities.models import Opportunity
    from app.opportunities.service import QUESTION_GAPS

    headers = signup(client, "oldfp")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    first_scan = scan_and_wait(client, headers, project_id)
    with SessionLocal() as s:  # rewrite the first scan's question gaps to the pre-grouping "{type}:{category}" format
        rows = s.scalars(select(Opportunity).where(Opportunity.scan_id == first_scan["id"], Opportunity.type.in_(QUESTION_GAPS))).all()
        assert rows
        for r in rows:
            s.execute(update(Opportunity).where(Opportunity.id == r.id).values(fingerprint=f"{r.type.lower()}:{r.evidence.get('category') or ''}".lower()))
        s.commit()

    scan_and_wait(client, headers, project_id)
    after = opportunities(client, headers, project_id)
    assert after and not [o for o in after if o["trend"] == "resolved" or o["status"] == "completed"]
    assert all(o["scan_id"] != first_scan["id"] for o in after)


def test_retest_asks_each_prompt_three_times_and_does_not_close_the_fix(client):
    from sqlalchemy import func, select

    from app.prompts.models import ScanPrompt

    headers = signup(client, "retest")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    full = scan_and_wait(client, headers, project_id)
    target = next(o for o in opportunities(client, headers, project_id) if o["related_prompts"])

    started = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/retest", headers=headers).json()
    assert started["status"] == target["status"] != "completed"  # starting a re-test proves nothing yet
    assert started["retest"]["before"]["scan_id"] == full["id"]
    done = client.get(f"{API}/projects/{project_id}/opportunities/{target['id']}", headers=headers).json()
    assert done["retest"]["status"] == "done" and done["retest"]["verdict"] in ("better", "worse", "too_early")
    assert (done["status"] == "completed") == (done["retest"]["verdict"] == "better")

    scans = client.get(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert scans[0]["kind"] == "retest"
    with SessionLocal() as s:
        per_prompt = s.execute(
            select(ScanPrompt.text, func.count()).where(ScanPrompt.scan_id == scans[0]["id"]).group_by(ScanPrompt.text)
        ).all()
        answers = s.scalar(select(func.count()).select_from(AIResponseRecord).where(AIResponseRecord.scan_id == scans[0]["id"]))
    assert per_prompt and {n for _, n in per_prompt} == {3}  # every prompt is stored three times
    assert answers == scans[0]["total_runs"] == done["retest"]["after"]["answers"]  # and every repeat is asked and counted
    assert done["retest"]["after"]["answers"] % 3 == 0
    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert dashboard["latest_scan"]["id"] == full["id"]  # a re-test never becomes the dashboard's scan


def test_retest_is_charged_and_checked_for_all_three_asks(client):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from sqlalchemy import update

    from app.billing.plans import PLANS
    from app.billing.service import credits_used
    from app.opportunities.models import Opportunity
    from app.projects.models import Project

    headers = signup(client, "retestcredits")
    project_id = make_project(client, headers)
    client.put(f"{API}/projects/{project_id}", json={"engines": ["chatgpt_search"]}, headers=headers)
    question = "best crm for startups"
    client.post(f"{API}/projects/{project_id}/prompts", json={"text": question, "category": "CATEGORY", "intent": "DISCOVERY"}, headers=headers)
    full = scan_and_wait(client, headers, project_id)
    with SessionLocal() as s:
        project = s.get(Project, project_id)
        opportunity = Opportunity(project_id=project.id, scan_id=full["id"], type="COMPETITOR_GAP", title="t", description="d",
                                  recommended_action="a", impact="HIGH", confidence=0.8, evidence={"prompts": [question]})
        s.add(opportunity)
        s.flush()
        old = Scan(project_id=project.id, status="completed", total_runs=1, created_at=datetime.now(timezone.utc) - timedelta(days=3),
                   credits=Decimal(PLANS["pro"].credits_per_month) - Decimal(str(credits_used(s, project.workspace_id))) - Decimal("2.5"))
        s.add(old)
        s.commit()
        opportunity_id, old_id = opportunity.id, old.id

    url = f"{API}/projects/{project_id}/opportunities/{opportunity_id}/retest"
    blocked = client.post(url, headers=headers)  # 2.5 credits left: one ask fits, three do not
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "PLAN_LIMIT"
    assert blocked.json()["error"]["message"].startswith("This scan needs 3 credits and 2.5 are left")

    with SessionLocal() as s:
        s.execute(update(Scan).where(Scan.id == old_id).values(credits=Scan.credits - Decimal("0.5")))
        s.commit()
    allowed = client.post(url, headers=headers)
    assert allowed.status_code == 200
    with SessionLocal() as s:
        retest_scan = s.get(Scan, allowed.json()["retest"]["scan_id"])
        assert (retest_scan.total_runs, retest_scan.credits) == (3, 3)


def test_only_a_better_verdict_marks_the_fix_completed(client, monkeypatch):
    headers = signup(client, "retestverdict")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_and_wait(client, headers, project_id)
    targets = [o for o in opportunities(client, headers, project_id) if o["related_prompts"]][:2]
    for target, result in zip(targets, ("worse", "better")):
        monkeypatch.setattr("app.opportunities.retest.verdict", lambda before, after, *rate, result=result: result)
        client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/retest", headers=headers)
        after = client.get(f"{API}/projects/{project_id}/opportunities/{target['id']}", headers=headers).json()
        assert after["retest"]["verdict"] == result
        assert after["status"] == ("completed" if result == "better" else target["status"])


def test_retest_verdict_needs_a_change_bigger_than_noise():
    from app.opportunities.retest import verdict

    counts = lambda answers, mentioned: {"answers": answers, "mentioned": mentioned}  # noqa: E731
    assert verdict(counts(10, 1), counts(30, 24)) == "better"  # 10% -> 80%
    assert verdict(counts(10, 8), counts(30, 3)) == "worse"  # 80% -> 10%
    assert verdict(counts(10, 4), counts(30, 14)) == "too_early"  # 40% -> 47%: noise
    assert verdict(None, counts(30, 20)) == "too_early"  # no full scan to compare with
    assert verdict(counts(0, 0), counts(30, 20)) == "too_early" and verdict(counts(10, 2), counts(0, 0)) == "too_early"
    # A zero "before" adds no variance on its own side; pooling keeps small samples from passing as a win.
    assert verdict(counts(2, 0), counts(6, 3)) == "too_early"  # 0% -> 50% on 2 and 6 answers: noise
    assert verdict(counts(2, 0), counts(6, 6)) == "better"  # 0% -> 100%
    assert verdict(counts(1, 0), counts(3, 3)) == "too_early"  # one answer before is not a baseline


def test_significance_pools_both_samples():
    from app.metrics.stats import significant

    assert significant(0.0, 2, 0.5, 6) is False and significant(0.0, 2, 4 / 6, 6) is False
    assert significant(0.0, 6, 4 / 18, 18) is False and significant(0.0, 10, 5 / 30, 30) is False
    assert significant(0.0, 10, 0.0, 30) is False and significant(1.0, 5, 1.0, 5) is False  # identical, no spread
    assert significant(0.1, 10, 0.8, 30) is True


def test_a_comparison_fix_is_judged_on_recommendations(monkeypatch):
    """A comparison gap is lost when the brand is named but not recommended, so its re-test is judged the same way."""
    from types import SimpleNamespace

    from app.opportunities import retest

    counts = lambda answers, mentioned, recommended: {"answers": answers, "mentioned": mentioned, "recommended": recommended}  # noqa: E731
    assert retest.verdict(counts(10, 10, 1), counts(30, 30, 24), "recommended") == "better"
    assert retest.verdict(counts(10, 10, 1), counts(30, 30, 24)) == "too_early"  # named every time, before and after

    def finish(category):
        opportunity = SimpleNamespace(status="open", evidence={"category": category, "retest": {
            "status": "running", "before": counts(10, 10, 1)}})
        session = SimpleNamespace(get=lambda model, pk: opportunity, scalars=lambda q: ["a vs b?"])
        monkeypatch.setattr(retest, "results_for", lambda session, scan_id, texts: counts(30, 30, 24))
        retest.finish_retest(session, SimpleNamespace(id=1, opportunity_id=7, completed_runs=30))
        return opportunity

    for category in ("COMPARISON", "COMPETITOR"):
        done = finish(category)
        assert done.evidence["retest"]["verdict"] == "better" and done.status == "completed"
    assert finish("USE_CASE").evidence["retest"]["verdict"] == "too_early"


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
            citations=[{"url": f"https://{d}/crm", "domain": d, "source_type": "review_site" if d == "g2.com" else "blog",
                        "is_brand_owned": False, "competitor_id": None} for d in domains],
        )
    found = detect([obs(0, True, False, [])] + [obs(i, False, True, ["g2.com", "zapier.com"]) for i in range(1, 4)], "Halden", {7: "Kiteline"})
    gap = next(f for f in found if f["type"] == "COMPETITOR_GAP")
    steps = " ".join(gap["evidence"]["steps"])
    assert "category discovery guide" in steps and '"best crm 1"' in steps and gap["evidence"]["effort"] == "M"
    assert "Get Halden reviewed on g2.com: AI cited https://g2.com/crm" in steps and "https://zapier.com/crm" in steps


def test_first_scan_sends_a_ready_email_once(client, outbox):
    from app.metrics.alerts import notify_first_scan

    headers = signup(client, "ready")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    first = scan_and_wait(client, headers, project_id)
    second = scan_and_wait(client, headers, project_id)
    with SessionLocal() as s:  # paid plans get the report email instead, so call the free trial's alert directly
        assert notify_first_scan(s, s.get(Scan, first["id"])) and not notify_first_scan(s, s.get(Scan, second["id"]))
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
    assert "Kiteline now wins &quot;best crm for startups&quot;" in mail["html"]


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
