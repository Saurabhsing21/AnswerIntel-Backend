"""Report PDFs in Cloudflare R2, with the S3 client faked: nothing here touches the network."""

import pytest

from app.common import storage
from app.common.config import settings
from app.common.database import SessionLocal
from app.reports import migrate_pdfs_to_r2
from app.reports.models import ReportPdf
from tests.conftest import API
from tests.test_reports import ready_project, run_scan


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        disposition = Params.get("ResponseContentDisposition", "")
        return f"https://signed.example/{Params['Key']}?exp={ExpiresIn}&cd={disposition}"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    for key in ("r2_account_id", "r2_bucket", "r2_access_key_id", "r2_secret_access_key"):
        monkeypatch.setattr(settings, key, "x")
    monkeypatch.setattr(storage, "_s3", lambda: fake)
    return fake


def new_report(client, name):
    headers, project_id = ready_project(client, name)
    run_scan(client, headers, project_id)
    report = client.post(f"{API}/projects/{project_id}/reports", json={"type": "manual"}, headers=headers).json()
    return headers, project_id, report["id"]


def test_r2_needs_all_four_settings(monkeypatch):
    assert not settings.r2_enabled
    for key in ("r2_account_id", "r2_bucket", "r2_access_key_id"):
        monkeypatch.setattr(settings, key, "x")
    assert not settings.r2_enabled
    monkeypatch.setattr(settings, "r2_secret_access_key", "x")
    assert settings.r2_enabled


def test_with_r2_the_pdf_is_uploaded_and_the_bytes_leave_the_database(client, s3):
    headers, project_id, report_id = new_report(client, "r2up")
    key = f"reports/{project_id}/{report_id}.pdf"
    assert s3.objects[key] == b"%PDF-1.7 stub"
    with SessionLocal() as session:
        row = session.get(ReportPdf, report_id)
        assert row.status == "ready" and row.storage_key == key and row.pdf is None


def test_export_redirects_to_a_five_minute_signed_url_for_owner_and_shared_link(client, s3):
    headers, project_id, report_id = new_report(client, "r2dl")
    base = f"{API}/projects/{project_id}/reports/{report_id}"
    key = f"reports/{project_id}/{report_id}.pdf"

    owner = client.get(f"{base}/export?format=pdf", headers=headers, follow_redirects=False)
    assert owner.status_code == 307
    assert owner.headers["location"].startswith(f"https://signed.example/{key}?exp=300")
    assert "AI%20Visibility%20Report" in owner.headers["location"]

    token = client.post(f"{base}/share", headers=headers).json()["token"]
    shared = client.get(f"{API}/shared/reports/{token}?format=pdf", follow_redirects=False)
    assert shared.status_code == 307 and shared.headers["location"].startswith(f"https://signed.example/{key}")


def test_without_r2_the_bytes_stay_in_the_database(client):
    headers, project_id, report_id = new_report(client, "r2off")
    with SessionLocal() as session:
        row = session.get(ReportPdf, report_id)
        assert row.storage_key is None and row.pdf == b"%PDF-1.7 stub"
    pdf = client.get(f"{API}/projects/{project_id}/reports/{report_id}/export?format=pdf", headers=headers, follow_redirects=False)
    assert pdf.status_code == 200 and pdf.content == b"%PDF-1.7 stub"


def test_deleting_a_project_deletes_its_stored_pdfs(client, s3):
    headers, project_id, report_id = new_report(client, "r2del")
    assert s3.objects
    assert client.delete(f"{API}/projects/{project_id}", headers=headers).status_code == 200
    assert not any(k.startswith(f"reports/{project_id}/") for k in s3.objects)


def test_migration_moves_database_pdfs_once(client, monkeypatch):
    headers, project_id, report_id = new_report(client, "r2mig")  # stored in the database: R2 is off
    fake = FakeS3()
    for key in ("r2_account_id", "r2_bucket", "r2_access_key_id", "r2_secret_access_key"):
        monkeypatch.setattr(settings, key, "x")
    monkeypatch.setattr(storage, "_s3", lambda: fake)

    assert migrate_pdfs_to_r2.migrate() >= 1
    key = f"reports/{project_id}/{report_id}.pdf"
    assert fake.objects[key] == b"%PDF-1.7 stub"
    with SessionLocal() as session:
        row = session.get(ReportPdf, report_id)
        assert row.storage_key == key and row.pdf is None
    assert migrate_pdfs_to_r2.migrate() == 0  # idempotent
