from app.scans.execution import run_scan
from app.worker.celery_app import celery_app


@celery_app.task(name="scans.run_scan")
def run_scan_task(scan_id: int) -> None:
    """Idempotent: the scan lock and stored-answer check make a redelivered job safe."""
    run_scan(scan_id)
