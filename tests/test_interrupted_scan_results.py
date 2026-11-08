"""A scan cut short by a restart still turns the answers it saved into a dashboard, an action plan and a report."""

from sqlalchemy import delete

from app.common.database import SessionLocal
from app.metrics.models import MetricSnapshot
from app.opportunities.models import Opportunity
from app.reports.models import Report
from app.scans.execution import recover_interrupted_scans
from app.scans.models import Scan
from tests.conftest import API, make_project, signup


def test_an_interrupted_scan_still_gets_its_dashboard_and_report(client):
    headers = signup(client, "interrupted")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan_id = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()["id"]

    # Make it look like the server died after saving answers but before finishing the scan.
    with SessionLocal() as session:
        session.execute(delete(Report).where(Report.scan_id == scan_id))
        session.execute(delete(Opportunity).where(Opportunity.scan_id == scan_id))
        session.execute(delete(MetricSnapshot).where(MetricSnapshot.scan_id == scan_id))
        scan = session.get(Scan, scan_id)
        scan.status, scan.completed_at = "running", None
        session.commit()
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()["has_data"] is False

    recover_interrupted_scans()

    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        assert scan.status == "partial" and scan.error_message == "Interrupted by a server restart."
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()["has_data"] is True
    reports = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert [r["scan_id"] for r in reports] == [scan_id]


def test_an_interrupted_retest_is_finished_so_its_page_stops_waiting(client):
    headers = signup(client, "interruptedretest")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    opportunities = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    target = next(o for o in opportunities if o["related_prompts"])
    started = client.post(f"{API}/projects/{project_id}/opportunities/{target['id']}/retest", headers=headers).json()

    # The server died mid re-test: the scan and the opportunity both still say "running".
    with SessionLocal() as session:
        scan = session.get(Scan, started["retest"]["scan_id"])
        scan.status, scan.completed_at = "running", None
        opportunity = session.get(Opportunity, target["id"])
        retest = {k: v for k, v in opportunity.evidence["retest"].items() if k not in ("after", "verdict", "completed_at")}
        opportunity.evidence = {**opportunity.evidence, "retest": {**retest, "status": "running"}}
        session.commit()

    recover_interrupted_scans()

    done = client.get(f"{API}/projects/{project_id}/opportunities/{target['id']}", headers=headers).json()
    assert done["retest"]["status"] == "done" and done["retest"]["after"]["answers"] > 0
    assert done["retest"]["verdict"] in ("better", "worse", "too_early")
