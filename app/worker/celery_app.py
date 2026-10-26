"""Celery app (PRD 56-57). Run a worker with: celery -A app.worker.celery_app worker -l info -Q scan"""

from celery import Celery
from celery.schedules import crontab

from app.common.config import settings

celery_app = Celery(
    "answerintel",
    # memory:// keeps imports and tests independent of Redis; the API only uses the broker when REDIS_URL is set.
    broker=settings.redis_url or "memory://",
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_default_queue="scan",
    task_acks_late=True,  # a job is only acknowledged once it finished, so a dead worker's job is redelivered
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # scans are long; do not hoard jobs behind a busy worker
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    # Scheduler: run with `celery -A app.worker.celery_app beat`. It only queues work (PRD 81).
    beat_schedule={
        "dispatch-scheduled-scans": {"task": "schedules.dispatch", "schedule": crontab(minute=0)},
        "requeue-stuck-scans": {"task": "schedules.requeue_stuck", "schedule": crontab(minute="*/10")},
        "purge-expired-data": {"task": "maintenance.purge_expired", "schedule": crontab(hour=3, minute=30)},
        "trial-notices": {"task": "billing.trial_notices", "schedule": crontab(hour=15, minute=0)},
        "free-nudges": {"task": "billing.free_nudges", "schedule": crontab(hour=15, minute=30)},
    },
)
