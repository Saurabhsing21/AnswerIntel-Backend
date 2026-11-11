"""Taking your data out and leaving (GDPR-style export and erasure)."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.analysis.models import Citation, CompetitorObservation, Mention
from app.billing import cashfree_client
from app.billing.models import Subscription
from app.common import storage
from app.common.errors import AppError
from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.models import Prompt
from app.providers.response_model import AIResponseRecord
from app.reports.models import Report, ReportPdf
from app.scans.models import Scan
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember


def _iso(value):
    return value.isoformat() if value else None


def _observation(row, **extra) -> dict:
    return {**extra, "mentioned": row.mentioned, "recommended": row.recommended, "position": row.position,
            "sentiment": row.sentiment, "reason": row.reason, "evidence": row.evidence}


def _scan_export(session: Session, scan: Scan, competitors: dict[int, str]) -> dict:
    """Each answer with how it was read. Raw provider JSON and cost fields are deliberately left out."""
    answers = session.scalars(select(AIResponseRecord).where(AIResponseRecord.scan_id == scan.id).order_by(AIResponseRecord.id)).all()
    ids = [a.id for a in answers]
    mentions = {m.ai_response_id: m for m in session.scalars(select(Mention).where(Mention.ai_response_id.in_(ids)))}
    observed: dict[int, list] = {}
    for o in session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id.in_(ids))):
        observed.setdefault(o.ai_response_id, []).append(_observation(o, competitor=competitors.get(o.competitor_id)))
    cited: dict[int, list] = {}
    for c in session.scalars(select(Citation).where(Citation.ai_response_id.in_(ids))):
        cited.setdefault(c.ai_response_id, []).append({"url": c.url, "title": c.title, "domain": c.domain, "is_brand_owned": c.is_brand_owned})
    return {
        "id": scan.id, "status": scan.status, "kind": scan.kind, "created_at": _iso(scan.created_at), "completed_at": _iso(scan.completed_at),
        "answers": [
            {
                "question": a.prompt, "engine": a.engine, "answer": a.response_text, "created_at": _iso(a.created_at),
                "brand": _observation(mentions[a.id], brand=mentions[a.id].brand_name) if a.id in mentions else None,
                "competitors": observed.get(a.id, []),
                "citations": cited.get(a.id, []),
            }
            for a in answers
        ],
    }


def export_data(session: Session, user: User) -> dict:
    owned = session.scalars(
        select(Workspace).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id, WorkspaceMember.role == "owner").order_by(Workspace.created_at)
    ).all()
    workspaces = []
    for workspace in owned:
        projects = []
        for project in session.scalars(select(Project).where(Project.workspace_id == workspace.id).order_by(Project.created_at)):
            competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
            names = {c.id: c.name for c in competitors}
            projects.append({
                "id": str(project.id), "brand_name": project.brand_name, "website": project.website, "description": project.description,
                "category": project.category, "country": project.country, "engines": project.engines, "aliases": project.aliases,
                "created_at": _iso(project.created_at),
                "questions": [
                    {"text": p.text, "category": p.category, "intent": p.intent, "active": p.is_active, "engines": p.engines}
                    for p in session.scalars(select(Prompt).where(Prompt.project_id == project.id).order_by(Prompt.id))
                ],
                "competitors": [{"name": c.name, "website": c.website, "aliases": c.aliases} for c in competitors],
                "scans": [_scan_export(session, s, names) for s in session.scalars(select(Scan).where(Scan.project_id == project.id).order_by(Scan.id))],
                "reports": [
                    {"id": r.id, "type": r.type, "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
                     "created_at": _iso(r.created_at), "content": r.content}
                    for r in session.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.id))
                ],
            })
        workspaces.append({"id": str(workspace.id), "name": workspace.name, "created_at": _iso(workspace.created_at), "projects": projects})
    return {
        "account": {"id": user.id, "email": user.email, "name": user.name, "created_at": _iso(user.created_at)},
        "workspaces": workspaces,
    }


def delete_account(session: Session, user: User) -> list[str]:
    """Removes the user and every workspace they alone own. Returns the R2 keys to delete once the commit succeeds.

    Nothing is transferred silently: a workspace with other people in it must be handed over or emptied first (409).
    Raises before touching anything if Cashfree can't cancel a subscription."""
    memberships = session.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    doomed, kept = [], []
    for m in memberships:
        owners = session.scalar(select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == m.workspace_id, WorkspaceMember.role == "owner"))
        if m.role == "owner" and owners == 1:
            doomed.append(m.workspace_id)
        else:
            kept.append(m.workspace_id)
    blocked = [
        name for wid in doomed
        if session.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == wid, WorkspaceMember.user_id != user.id))
        for name in [session.scalar(select(Workspace.name).where(Workspace.id == wid))]
    ]
    if blocked:
        raise AppError(409, "WORKSPACE_HAS_MEMBERS",
                       f"You are the only owner of {', '.join(blocked)}, which has other members. Make someone else an owner or remove the members first.")

    subscriptions = session.scalars(select(Subscription).where(
        Subscription.workspace_id.in_(doomed), Subscription.cashfree_subscription_id.is_not(None), Subscription.status != "canceled")).all()
    for sub in subscriptions:
        cashfree_client.cancel_subscription(sub.cashfree_subscription_id)

    keys = session.scalars(
        select(ReportPdf.storage_key).join(Report, Report.id == ReportPdf.report_id).join(Project, Project.id == Report.project_id)
        .where(Project.workspace_id.in_(doomed), ReportPdf.storage_key.is_not(None))
    ).all()
    # Projects they started in workspaces that carry on stay with the team: projects.user_id would otherwise cascade them away.
    for wid in kept:
        heir = session.scalar(select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == wid, WorkspaceMember.user_id != user.id).order_by(WorkspaceMember.role != "owner", WorkspaceMember.created_at))
        session.execute(update(Project).where(Project.workspace_id == wid, Project.user_id == user.id).values(user_id=heir))
    session.execute(delete(Workspace).where(Workspace.id.in_(doomed)))
    session.execute(delete(User).where(User.id == user.id))  # tokens and memberships cascade; the cost ledger keeps its rows
    return list(keys)


def delete_files(keys: list[str]) -> None:
    for key in keys:
        storage.delete(key)
