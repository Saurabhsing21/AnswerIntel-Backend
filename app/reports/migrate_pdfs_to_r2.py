"""Moves PDFs stored in the database to R2: `python -m app.reports.migrate_pdfs_to_r2`. Safe to repeat: rows that
already have a storage key are skipped."""

from sqlalchemy import select

from app.common import storage
from app.common.config import settings
from app.common.database import SessionLocal
from app.reports.models import Report, ReportPdf


def migrate() -> int:
    if not settings.r2_enabled:
        raise SystemExit("R2 is not configured (R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY).")
    moved = 0
    with SessionLocal() as session:
        rows = session.execute(
            select(ReportPdf, Report.project_id)
            .join(Report, Report.id == ReportPdf.report_id)
            .where(ReportPdf.storage_key.is_(None), ReportPdf.pdf.is_not(None))
        ).all()
        for row, project_id in rows:
            key = f"reports/{project_id}/{row.report_id}.pdf"
            storage.put_pdf(key, row.pdf)
            row.storage_key, row.pdf = key, None
            session.commit()  # one at a time so an interrupted run keeps its progress
            moved += 1
    return moved


if __name__ == "__main__":
    print(f"Moved {migrate()} PDFs to R2.")
