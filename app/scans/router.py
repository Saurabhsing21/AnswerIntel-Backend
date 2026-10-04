from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.common.database import SessionLocal
from app.projects.models import Project
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.scans.service import ScanService
from app.users.models import User


router = APIRouter(
    prefix="/projects/{project_id}/scans",
    tags=["scans"],
)


def get_user_project(session, project_id: UUID, user_id: int):
    return session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )


def get_user_scan(session, project_id: UUID, scan_id: int, user_id: int):
    project = get_user_project(session, project_id, user_id)
    if not project:
        return None

    return session.scalar(
        select(Scan).where(
            Scan.id == scan_id,
            Scan.project_id == project.id,
        )
    )


@router.post("")
def create_scan(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_user_project(session, project_id, current_user.id)

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        scan = ScanService().create_scan(
            session=session,
            project=project,
        )

        session.commit()

        return {
            "id": scan.id,
            "project_id": str(scan.project_id),
            "status": scan.status,
        }


@router.get("/{scan_id}")
def get_scan(
    project_id: UUID,
    scan_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        scan = get_user_scan(session, project_id, scan_id, current_user.id)

        if not scan:
            raise HTTPException(
                status_code=404,
                detail="Scan not found",
            )

        return {
            "id": scan.id,
            "project_id": str(scan.project_id),
            "status": scan.status,
            "started_at": scan.started_at,
            "completed_at": scan.completed_at,
        }


@router.get("/{scan_id}/prompts")
def list_scan_prompts(
    project_id: UUID,
    scan_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        scan = get_user_scan(session, project_id, scan_id, current_user.id)

        if not scan:
            raise HTTPException(
                status_code=404,
                detail="Scan not found",
            )

        prompts = session.scalars(
            select(ScanPrompt)
            .where(ScanPrompt.scan_id == scan.id)
            .order_by(ScanPrompt.id)
        ).all()

        return [
            {
                "id": prompt.id,
                "scan_id": prompt.scan_id,
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
        scan = get_user_scan(session, project_id, scan_id, current_user.id)

        if not scan:
            raise HTTPException(
                status_code=404,
                detail="Scan not found",
            )

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
                "provider": record.provider,
                "model": record.model,
                "prompt": record.prompt,
                "response_text": record.response_text,
                "raw_response": record.raw_response,
                "created_at": record.created_at,
            }
            for record in records
        ]
