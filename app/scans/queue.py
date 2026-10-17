import logging
from datetime import datetime, timezone

from fastapi import BackgroundTasks

from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.scans.execution import run_scan
from app.scans.models import Scan

log = logging.getLogger(__name__)


def enqueue_scan(scan_id: int, background_tasks: BackgroundTasks) -> None:
    """Hand a committed scan to a Celery worker, or run it in-process when no Redis is configured."""
    if not settings.redis_url:
        background_tasks.add_task(run_scan, scan_id)
        return
    from app.worker.tasks import run_scan_task

    try:
        run_scan_task.delay(scan_id)
    except Exception:
        log.exception("Could not queue scan %s", scan_id)
        # Never leave a scan "queued" forever: it would block the project from scanning again.
        with SessionLocal() as session:
            scan = session.get(Scan, scan_id)
            if scan and scan.status == "queued":
                scan.status = "failed"
                scan.error_message = "The job queue is unavailable."
                scan.completed_at = datetime.now(timezone.utc)
                session.commit()
        raise AppError(503, "QUEUE_UNAVAILABLE", "Scans cannot be started right now. Please try again shortly.")
