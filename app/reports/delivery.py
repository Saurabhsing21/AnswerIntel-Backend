import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.billing.plans import entitlements
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.projects.models import Project
from app.reports.email import send_report_email
from app.reports.models import Report
from app.reports.pdf_jobs import queue_report_pdf
from app.reports.email_render import build_report_email
from app.reports.service import create_report
from app.scans.models import Scan
from app.users.models import User

log = logging.getLogger(__name__)


def deliver_scan_report(scan_id: int, report_type: str) -> None:
    """The report for a finished full scan, emailed to the project owner. At most one per scan, paid plans only
    (the free trial sees a locked preview in the app instead)."""
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if not scan or scan.kind != "full" or scan.status not in ("completed", "partial"):
            return
        if session.scalar(select(Report.id).where(Report.scan_id == scan_id)):
            return  # redelivered job: the report already exists
        project = session.get(Project, scan.project_id)
        if not entitlements(session, project.workspace_id).pro:
            return
        report = create_report(session, project, report_type)
        session.commit()
        report_id = report.id
    # The owner is emailed by the PDF job once the PDF exists (or failed), so the attachment is not raced.
    queue_report_pdf(report_id, email_owner=True)


def email_report_to_owner(report_id: int) -> None:
    """Emails the report to the project owner, PDF attached when ready, link only otherwise. Once per report."""
    with SessionLocal() as session:
        report = session.get(Report, report_id)
        if not report or report.emailed_at:
            return
        owner = session.get(User, session.get(Project, report.project_id).user_id)
        try:
            subject, html, attachments = build_report_email(session, report)
            send_report_email(owner.email, subject, html, attachments or None)
        except AppError as exc:
            log.info("Report %s kept but not emailed: %s", report.id, exc.code)
            return
        report.emailed_at = datetime.now(timezone.utc)
        session.commit()
