"""Scheduler (PRD 81): decides what is due and queues it. It never runs a scan itself."""

import logging
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.billing.plans import entitlements
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.projects.models import Project
from app.scans.models import Scan
from app.scans.service import ScanService
from app.schedules.models import ScanSchedule

log = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=15)


def latest_slot(now: datetime, day_of_week: int, hour: int) -> datetime:
    """The most recent weekly occurrence of (day_of_week, hour) at or before `now`."""
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=(now.weekday() - day_of_week) % 7)
    return slot - timedelta(days=7) if slot > now else slot


def dispatch_due_scans(
    now: datetime, enqueue: Callable[[int, bool], None], project_ids: Collection[UUID] | None = None
) -> list[int]:
    """Create and queue a scan for every enabled schedule whose slot has arrived and not yet fired.
    `project_ids` limits the run to those projects (the scheduler passes none and serves everyone).

    A slot that cannot fire now (scan already running, no prompts, daily limit, plan) is retried on the next
    run, because last_run_at only advances when a scan was actually created.
    """
    started: list[int] = []
    with SessionLocal() as session:
        query = select(ScanSchedule).where(ScanSchedule.enabled)
        if project_ids is not None:
            query = query.where(ScanSchedule.project_id.in_(project_ids))
        for schedule in session.scalars(query).all():
            slot = latest_slot(now, schedule.day_of_week, schedule.hour)
            if slot < schedule.starts_at or (schedule.last_run_at and schedule.last_run_at >= slot):
                continue
            project = session.get(Project, schedule.project_id)
            if not entitlements(session, project.workspace_id).schedules:
                continue  # the workspace moved to a plan without schedules; the schedule waits for an upgrade
            try:
                scan = ScanService().start_scan(session, project)
            except AppError as exc:
                session.rollback()
                log.info("Scheduled scan for project %s skipped: %s", schedule.project_id, exc.code)
                continue
            schedule.last_run_at = now
            session.commit()
            try:
                enqueue(scan.id, True)  # True = send the weekly report when the scan finishes
            except Exception:
                log.exception("Could not queue scheduled scan %s; the sweeper will retry", scan.id)
            started.append(scan.id)
    return started


def requeue_stuck_scans(now: datetime, enqueue: Callable[[int], None]) -> list[int]:
    """Re-queue scans still 'queued' long after creation: their job was lost (worker crash, broker flush).

    Safe if the original job is merely slow: running a scan twice is a no-op (status check + scan lock)."""
    with SessionLocal() as session:
        ids = list(session.scalars(select(Scan.id).where(Scan.status == "queued", Scan.created_at < now - STUCK_AFTER)))
    for scan_id in ids:
        enqueue(scan_id)
    return ids
