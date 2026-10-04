from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.common.database import SessionLocal
from app.projects.models import Project
from app.scans.service import ScanService
from app.users.models import User


router = APIRouter(
    prefix="/projects/{project_id}/scans",
    tags=["scans"],
)


@router.post("")
def create_scan(
    project_id: int,
    current_user: User = Depends(get_current_user),
):

    with SessionLocal() as session:

        project = session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == current_user.id,
            )
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        scan_service = ScanService()

        scan = scan_service.create_scan(
            session=session,
            project=project,
        )

        session.commit()

        return {
            "id": scan.id,
            "project_id": scan.project_id,
            "status": scan.status,
        }