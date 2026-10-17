"""PRD sections 43, 55, 71: weekly founder report, shareable link, export, email."""

from datetime import date

from app.common.config import settings
from tests.conftest import API, make_project, signup


def ready_project(client, prefix="rep", brand="Halden"):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    if brand != "Halden":
        client.put(f"{API}/projects/{project_id}", json={"brand_name": brand}, headers=headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    return headers, project_id


def run_scan(client, headers, project_id):
    return client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()


def test_report_needs_scan_data(client):
    headers, project_id = ready_project(client)
    response = client.post(f"{API}/projects/{project_id}/reports", json={"type": "weekly"}, headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "NO_SCAN_DATA"


def test_weekly_report_content_and_immutability(client):
    headers, project_id = ready_project(client)
    first_scan = run_scan(client, headers, project_id)
    created = client.post(f"{API}/projects/{project_id}/reports", json={"type": "weekly"}, headers=headers)
    assert created.status_code == 200
    report = created.json()
    assert report["type"] == "weekly" and report["status"] == "ready" and report["scan_id"] == first_scan["id"]
    assert (date.fromisoformat(report["period_end"]) - date.fromisoformat(report["period_start"])).days == 7

    content = report["content"]
    assert content["brand"] == "Halden"
    assert 0 <= content["visibility"]["mention_rate"] <= 1
    assert content["competitors"] and content["summary"]
    assert any("mention" in line.lower() for line in content["summary"])

    # Reports are historical records: later scans never rewrite them.
    run_scan(client, headers, project_id)
    fetched = client.get(f"{API}/projects/{project_id}/reports/{report['id']}", headers=headers).json()
    assert fetched["content"] == content
    second = client.post(f"{API}/projects/{project_id}/reports", json={"type": "monthly"}, headers=headers).json()
    assert second["scan_id"] != report["scan_id"]
    listed = client.get(f"{API}/projects/{project_id}/reports", headers=headers).json()
    assert [r["id"] for r in listed] == [second["id"], report["id"]]
    assert "content" not in listed[0]


def test_reports_are_private(client):
    headers, project_id = ready_project(client, "repowner")
    run_scan(client, headers, project_id)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "manual"}, headers=headers).json()
    stranger = signup(client, "repstranger")
    base = f"{API}/projects/{project_id}/reports"
    assert client.get(base, headers=stranger).status_code == 404
    assert client.get(f"{base}/{report['id']}", headers=stranger).status_code == 404
    assert client.post(f"{base}/{report['id']}/share", headers=stranger).status_code == 404
    assert client.post(f"{base}/{report['id']}/send", headers=stranger).status_code == 404


def test_share_link_public_html_pdf_and_revoke(client):
    headers, project_id = ready_project(client, "repshare", brand="Halden <script>alert(1)</script>")
    run_scan(client, headers, project_id)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "weekly"}, headers=headers).json()
    base = f"{API}/projects/{project_id}/reports/{report['id']}"

    assert client.get(f"{API}/shared/reports/not-a-real-token").status_code == 404
    token = client.post(f"{base}/share", headers=headers).json()["token"]

    public = client.get(f"{API}/shared/reports/{token}")  # no auth header
    assert public.status_code == 200 and public.json()["content"]["brand"].startswith("Halden")
    assert "user_id" not in public.text and "project_id" not in public.text

    html = client.get(f"{API}/shared/reports/{token}?format=html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<script>alert(1)</script>" not in html.text and "&lt;script&gt;" in html.text

    pdf = client.get(f"{API}/shared/reports/{token}?format=pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    owner_pdf = client.get(f"{base}/export?format=pdf", headers=headers)
    assert owner_pdf.status_code == 200 and owner_pdf.content.startswith(b"%PDF")

    assert client.delete(f"{base}/share", headers=headers).status_code == 200
    assert client.get(f"{API}/shared/reports/{token}").status_code == 404


def test_email_report(client, monkeypatch):
    headers, project_id = ready_project(client, "repmail")
    run_scan(client, headers, project_id)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "weekly"}, headers=headers).json()
    url = f"{API}/projects/{project_id}/reports/{report['id']}/send"

    monkeypatch.setattr(settings, "resend_api_key", "")
    not_configured = client.post(url, headers=headers)
    assert not_configured.status_code == 503 and not_configured.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"

    sent = {}

    class FakeResponse:
        status_code = 200

    def fake_post(endpoint, json, headers, timeout):
        sent.update(endpoint=endpoint, payload=json, auth=headers["Authorization"])
        return FakeResponse()

    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr("app.reports.email.httpx.post", fake_post)
    ok = client.post(url, headers=headers)
    assert ok.status_code == 200 and ok.json()["sent"] is True
    assert sent["endpoint"].endswith("/emails") and sent["auth"] == "Bearer re_test_key"
    assert sent["payload"]["to"][0].endswith("@example.com")
    assert "Halden" in sent["payload"]["subject"]
    refreshed = client.get(f"{API}/projects/{project_id}/reports/{report['id']}", headers=headers).json()
    assert refreshed["emailed_at"] is not None
