from uuid import UUID

import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import Response
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.analysis.models import Citation, CompetitorObservation, Mention
from app.common.access import get_owned_project
from app.competitors.models import Competitor
from app.common.database import SessionLocal
from app.billing.plans import entitlements, require_pro
from app.common.errors import AppError
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord
from app.scans.queue import enqueue_scan
from app.scans.models import Scan
from app.scans.service import ScanService
from app.users.models import User

router = APIRouter(
    prefix="/projects/{project_id}/scans",
    tags=["scans"],
)


def serialize(scan: Scan) -> dict:
    done = scan.completed_runs + scan.failed_runs
    return {
        "id": scan.id,
        "project_id": str(scan.project_id),
        "status": scan.status,
        "kind": scan.kind,  # "retest" = only one opportunity's prompts
        "opportunity_id": scan.opportunity_id,
        "provider": scan.provider,
        "simulated": scan.provider == "simulated",
        "total_runs": scan.total_runs,
        "completed_runs": scan.completed_runs,
        "failed_runs": scan.failed_runs,
        "progress": round(done / scan.total_runs, 4) if scan.total_runs else 0,
        "error_message": scan.error_message,
        "started_at": scan.started_at,
        "completed_at": scan.completed_at,
        "created_at": scan.created_at,
    }


def get_owned_scan(session, project_id: UUID, scan_id: int, user_id: int) -> Scan:
    project = get_owned_project(session, project_id, user_id)
    scan = session.scalar(select(Scan).where(Scan.id == scan_id, Scan.project_id == project.id))
    if not scan:
        raise AppError(404, "SCAN_NOT_FOUND", "Scan not found.")
    return scan


@router.post("")
def create_scan(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        if current_user.email_verified_at is None and entitlements(session, project.workspace_id).plan == "free":
            # The free scan costs real money: one per confirmed inbox, not one per throwaway address.
            raise AppError(403, "EMAIL_NOT_VERIFIED", "Confirm your email to run your free scan. We sent you a link.")
        scan = ScanService().start_scan(session=session, project=project)
        session.commit()
        session.refresh(scan)
        # Runs after the response is sent (worker queue, or in-process without Redis); the client polls GET /scans/{id}.
        enqueue_scan(scan.id, background_tasks)
        return serialize(scan)


@router.get("")
def list_scans(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        scans = session.scalars(select(Scan).where(Scan.project_id == project.id).order_by(Scan.id.desc())).all()
        return [serialize(s) for s in scans]


@router.get("/{scan_id}")
def get_scan(
    project_id: UUID,
    scan_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        return serialize(get_owned_scan(session, project_id, scan_id, current_user.id))


@router.get("/{scan_id}/prompts")
def list_scan_prompts(
    project_id: UUID,
    scan_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        scan = get_owned_scan(session, project_id, scan_id, current_user.id)
        prompts = session.scalars(
            select(ScanPrompt)
            .where(ScanPrompt.scan_id == scan.id)
            .order_by(ScanPrompt.id)
        ).all()
        return [
            {
                "id": prompt.id,
                "scan_id": prompt.scan_id,
                "prompt_id": prompt.prompt_id,
                "text": prompt.text,
                "category": prompt.category,
                "intent": prompt.intent,
                "created_at": prompt.created_at,
            }
            for prompt in prompts
        ]


@router.get("/{scan_id}/responses")
def list_scan_responses(
    project_id: UUID,
    scan_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        scan = get_owned_scan(session, project_id, scan_id, current_user.id)
        records = session.scalars(
            select(AIResponseRecord)
            .where(AIResponseRecord.scan_id == scan.id)
            .order_by(AIResponseRecord.id)
        ).all()
        return [
            {
                "id": record.id,
                "scan_id": record.scan_id,
                "scan_prompt_id": record.scan_prompt_id,
                "engine": record.engine,
                "provider": record.provider,
                "model": record.model,
                "prompt": record.prompt,
                "response_text": record.response_text,
                "raw_response": record.raw_response,
                "latency_ms": record.latency_ms,
                "created_at": record.created_at,
            }
            for record in records
        ]


CSV_COLUMNS = ["prompt", "category", "engine", "mentioned", "recommended", "position", "sentiment", "reason",
               "evidence", "competitors_recommended", "citations"]


@router.get("/{scan_id}/export.csv")
def export_scan_csv(project_id: UUID, scan_id: int, current_user: User = Depends(get_current_user)):
    """Every answer of a scan as one spreadsheet row: the raw material behind the dashboard."""
    with SessionLocal() as session:
        scan = get_owned_scan(session, project_id, scan_id, current_user.id)
        require_pro(entitlements(session, get_owned_project(session, project_id, current_user.id).workspace_id), "CSV exports")
        names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == scan.project_id))}
        rows = session.execute(
            select(AIResponseRecord, ScanPrompt, Mention)
            .join(ScanPrompt, ScanPrompt.id == AIResponseRecord.scan_prompt_id)
            .outerjoin(Mention, Mention.ai_response_id == AIResponseRecord.id)
            .where(AIResponseRecord.scan_id == scan.id)
            .order_by(ScanPrompt.id, AIResponseRecord.engine)
        ).all()
        ids = [r.AIResponseRecord.id for r in rows]
        picks: dict[int, list[str]] = {}
        for o in session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id.in_(ids), CompetitorObservation.recommended)):
            picks.setdefault(o.ai_response_id, []).append(names.get(o.competitor_id, ""))
        sources: dict[int, list[str]] = {}
        for c in session.scalars(select(Citation).where(Citation.ai_response_id.in_(ids))):
            sources.setdefault(c.ai_response_id, []).append(c.url)

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_COLUMNS)
        for record, prompt, mention in rows:
            writer.writerow([
                prompt.text, prompt.category, record.engine,
                mention.mentioned if mention else "", mention.recommended if mention else "",
                mention.position if mention and mention.position else "", mention.sentiment if mention else "",
                mention.reason if mention else "", mention.evidence if mention else "",
                "; ".join(picks.get(record.id, [])), " ".join(sources.get(record.id, [])),
            ])
        filename = f"seenlens-scan-{scan.id}.csv"
        return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
