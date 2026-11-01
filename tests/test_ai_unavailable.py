"""With no AI service behind it, the product says so: no simulated answers, no template prompts, no canned drafts."""

from sqlalchemy import select

from app.common.database import SessionLocal
from app.scans.execution import ScanExecutionService
from app.scans.models import Scan
from tests.conftest import API, make_project, signup

MESSAGE = "We couldn't reach the AI service. Try again in a minute."


def test_generating_prompts_without_ai_is_a_503(client, ai_down):
    headers = signup(client, "noai-prompts")
    project_id = make_project(client, headers)
    for path, body in (("generate", None), ("suggest", {"instructions": "agencies", "count": 4})):
        response = client.post(f"{API}/projects/{project_id}/prompts/{path}", json=body, headers=headers)
        assert response.status_code == 503, path
        assert response.json()["error"] == {"code": "AI_UNAVAILABLE", "message": MESSAGE}
    assert client.get(f"{API}/projects/{project_id}/prompts", headers=headers).json() == []  # no template prompts saved


def test_a_scan_without_ai_ends_failed_with_the_message(client, ai_down):
    headers = signup(client, "noai-scan")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts", json={"text": "Best CRM for startups?", "category": "CATEGORY", "intent": "DISCOVERY"}, headers=headers)
    scan_id = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()["id"]
    ScanExecutionService().run(scan_id)
    with SessionLocal() as session:
        scan = session.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan.status == "failed" and scan.error_message == MESSAGE
        assert scan.completed_runs == 0


def test_the_free_check_without_ai_fails_instead_of_inventing_answers(ai_down):
    from app.freecheck import service

    try:
        service._check("Halden", "halden.co", "CRM software", "US")
    except Exception as exc:
        assert getattr(exc, "code", "") == "AI_UNAVAILABLE"
    else:
        raise AssertionError("expected AI_UNAVAILABLE")
