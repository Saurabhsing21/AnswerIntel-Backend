"""Email the workspace owners when a scan shows a real drop in visibility (bigger than run-to-run noise)."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.emails import notify_owners
from app.metrics.models import MetricSnapshot
from app.metrics.stats import significant
from app.projects.models import Project
from app.scans.models import Scan

log = logging.getLogger(__name__)

WATCHED = {"recommendation_rate": "recommendation rate", "mention_rate": "mention rate"}
MIN_DROP = 0.05  # five points; smaller moves are not worth an email


def visibility_drops(session: Session, scan: Scan) -> list[str]:
    """Lines describing each watched rate that fell for real since the previous scan."""
    latest, previous = (session.scalars(
        select(MetricSnapshot).where(MetricSnapshot.project_id == scan.project_id).order_by(MetricSnapshot.scan_id.desc()).limit(2)
    ).all() + [None, None])[:2]
    if not latest or not previous or latest.scan_id != scan.id:
        return []
    lines = []
    for key, label in WATCHED.items():
        before, after = getattr(previous, key), getattr(latest, key)
        if before - after >= MIN_DROP and significant(before, previous.total_responses, after, latest.total_responses):
            lines.append(f"Your {label} fell from {round(before * 100)}% to {round(after * 100)}%.")
    return lines


def alert_on_drop(session: Session, scan: Scan) -> bool:
    lines = visibility_drops(session, scan)
    if not lines:
        return False
    project = session.get(Project, scan.project_id)
    notify_owners(
        session, project.workspace_id, f"AI visibility dropped for {project.brand_name}",
        " ".join(lines) + " Open SeenLens to see which questions you lost and who AI recommends instead.",
    )
    return True
