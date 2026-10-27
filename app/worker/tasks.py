from datetime import datetime, timezone

from app.billing.emails import send_free_nudges, send_trial_notices
from app.common.config import settings
from app.scans.execution import run_scan
from app.scans.retention import purge_expired
from app.schedules.service import dispatch_due_scans, requeue_stuck_scans
from app.worker.celery_app import celery_app


@celery_app.task(name="scans.run_scan")
def run_scan_task(scan_id: int, send_report: bool = False) -> None:
    """Idempotent: the scan lock and stored-answer check make a redelivered job safe.
    `send_report` marks a scheduled scan, whose report is the weekly one."""
    run_scan(scan_id, "weekly" if send_report else "manual")


@celery_app.task(name="schedules.dispatch")
def dispatch_scheduled_scans_task() -> list[int]:
    return dispatch_due_scans(datetime.now(timezone.utc), lambda scan_id, report: run_scan_task.delay(scan_id, report))


@celery_app.task(name="maintenance.purge_expired")
def purge_expired_task() -> dict:
    return purge_expired(datetime.now(timezone.utc), settings.raw_response_retention_days)


@celery_app.task(name="billing.trial_notices")
def trial_notices_task() -> dict:
    return send_trial_notices(datetime.now(timezone.utc))


@celery_app.task(name="billing.free_nudges")
def free_nudges_task() -> dict:
    return send_free_nudges(datetime.now(timezone.utc))


@celery_app.task(name="schedules.requeue_stuck")
def requeue_stuck_scans_task() -> list[int]:
    return requeue_stuck_scans(datetime.now(timezone.utc), lambda scan_id: run_scan_task.delay(scan_id))
