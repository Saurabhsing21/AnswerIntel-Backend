"""Email the workspace owners when a scan shows a real drop in visibility (bigger than run-to-run noise)."""

import logging

from sqlalchemy import func, select
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
        "Your latest scan shows AI recommending you less often. See which questions you lost and who AI picks instead.",
        path=f"/projects/{project.id}", button="See what changed", items=lines,
    )
    return True


def overtakes(session: Session, scan: Scan) -> list[tuple[str, str]]:
    """(prompt, competitor) pairs: questions where you were recommended last scan, and a competitor is now
    recommended while you are not, on any engine."""
    from app.analysis.models import CompetitorObservation, Mention
    from app.competitors.models import Competitor
    from app.prompts.models import ScanPrompt
    from app.providers.response_model import AIResponseRecord

    previous = session.scalar(
        select(MetricSnapshot.scan_id).where(MetricSnapshot.project_id == scan.project_id, MetricSnapshot.scan_id < scan.id)
        .order_by(MetricSnapshot.scan_id.desc())
    )
    if previous is None:
        return []

    def by_prompt(scan_id: int) -> tuple[dict[str, bool], dict[str, set[int]]]:
        you: dict[str, bool] = {}
        rivals: dict[str, set[int]] = {}
        rows = session.execute(
            select(ScanPrompt.text, Mention.recommended, AIResponseRecord.id)
            .join(AIResponseRecord, AIResponseRecord.scan_prompt_id == ScanPrompt.id)
            .join(Mention, Mention.ai_response_id == AIResponseRecord.id)
            .where(ScanPrompt.scan_id == scan_id)
        ).all()
        response_prompt = {rid: text for text, _, rid in rows}
        for text, recommended, _ in rows:
            you[text] = you.get(text, False) or recommended
        for o in session.scalars(select(CompetitorObservation).where(
            CompetitorObservation.ai_response_id.in_(list(response_prompt)), CompetitorObservation.recommended
        )):
            rivals.setdefault(response_prompt[o.ai_response_id], set()).add(o.competitor_id)
        return you, rivals

    before, _ = by_prompt(previous)
    now, rivals = by_prompt(scan.id)
    names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
    return [
        (text, names[cid])
        for text, was in before.items()
        if was and text in now and not now[text]
        for cid in sorted(rivals.get(text, set())) if cid in names
    ]


def alert_on_overtake(session: Session, scan: Scan) -> bool:
    found = overtakes(session, scan)
    if not found:
        return False
    project = session.get(Project, scan.project_id)
    items = [f'{name} now wins "{text}"' for text, name in found[:5]]
    if len(found) > 5:
        items.append(f"and {len(found) - 5} more questions")
    notify_owners(
        session, project.workspace_id, f"A competitor overtook {project.brand_name}",
        f"AI used to recommend {project.brand_name} on these questions and now recommends a competitor instead.",
        path=f"/projects/{project.id}/opportunities", button="See the answers and the fix", items=items,
    )
    return True


def notify_first_scan(session: Session, scan: Scan) -> bool:
    """Tells the owners their first scan of a project is ready (it takes a few minutes, so people leave)."""
    full_scans = session.scalar(
        select(func.count()).select_from(Scan).where(Scan.project_id == scan.project_id, Scan.kind == "full", Scan.id <= scan.id)
    )
    snapshot = session.scalar(select(MetricSnapshot).where(MetricSnapshot.scan_id == scan.id))
    if full_scans != 1 or not snapshot:
        return False
    project = session.get(Project, scan.project_id)
    notify_owners(
        session, project.workspace_id, f"Your first scan of {project.brand_name} is ready",
        f"We asked AI your buyers' questions {snapshot.total_responses} times. Here is how often it brought up {project.brand_name}, "
        "who it picks instead, and what to fix first.",
        path=f"/projects/{project.id}", button="See your results",
        stats=[(f"{round(snapshot.mention_rate * 100)}%", "mentioned you"),
               (f"{round(snapshot.recommendation_rate * 100)}%", "recommended you"),
               (str(snapshot.total_responses), "AI answers")],
    )
    return True
