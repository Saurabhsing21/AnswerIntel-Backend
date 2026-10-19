import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.billing.emails import send_trial_notices
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.projects.models import Project
from app.reports.email import send_report_email
from app.reports.models import Report
from app.reports.render import render_html
from app.reports.service import create_report, report_title
from app.scans.execution import run_scan
from app.scans.models import Scan
from app.scans.retention import purge_expired
from app.schedules.service import dispatch_due_scans, requeue_stuck_scans
from app.users.models import User
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)


def deliver_weekly_report(scan_id: int) -> None:
    """Weekly founder report for a finished scheduled scan. Sent at most once per scan."""
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if not scan or scan.status not in ("completed", "partial"):
            return
        if session.scalar(select(Report.id).where(Report.scan_id == scan_id, Report.type == "weekly")):
            return  # redelivered job: the report already exists
        project = session.get(Project, scan.project_id)
        report = create_report(session, project, "weekly")
        session.commit()
        owner = session.get(User, project.user_id)
        try:
            send_report_email(owner.email, report_title(report), render_html(report.content, report_title(report)))
        except AppError as exc:
            log.info("Weekly report %s kept but not emailed: %s", report.id, exc.code)
            return
        report.emailed_at = datetime.now(timezone.utc)
        session.commit()


@celery_app.task(name="scans.run_scan")
def run_scan_task(scan_id: int, send_report: bool = False) -> None:
    """Idempotent: the scan lock and stored-answer check make a redelivered job safe."""
    run_scan(scan_id)
    if send_report:
        deliver_weekly_report(scan_id)


@celery_app.task(name="schedules.dispatch")
def dispatch_scheduled_scans_task() -> list[int]:
    return dispatch_due_scans(datetime.now(timezone.utc), lambda scan_id, report: run_scan_task.delay(scan_id, report))


@celery_app.task(name="maintenance.purge_expired")
def purge_expired_task() -> dict:
    return purge_expired(datetime.now(timezone.utc), settings.raw_response_retention_days)


@celery_app.task(name="billing.trial_notices")
def trial_notices_task() -> dict:
    return send_trial_notices(datetime.now(timezone.utc))


@celery_app.task(name="schedules.requeue_stuck")
def requeue_stuck_scans_task() -> list[int]:
    return requeue_stuck_scans(datetime.now(timezone.utc), lambda scan_id: run_scan_task.delay(scan_id))
