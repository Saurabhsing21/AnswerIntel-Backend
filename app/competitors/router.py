from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.common.access import project_access
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from sqlalchemy import func

from app.common.config import settings
from app.common.errors import AppError
from app.competitors.schemas import CompetitorCreate, CompetitorUpdate
from app.projects.models import Project
from app.users.models import User


router = APIRouter(
    prefix="/projects/{project_id}/competitors",
    tags=["Competitors"],
)


def get_user_project(
    session,
    project_id: UUID,
    user_id: int,
):
    return session.scalar(
        select(Project).where(
            Project.id == project_id,
            project_access(user_id),
        )
    )


@router.post("")
def add_competitor(
    project_id: UUID,
    request: CompetitorCreate,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:

        project = get_user_project(
            session,
            project_id,
            current_user.id,
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        count = session.scalar(
            select(func.count()).select_from(Competitor).where(Competitor.project_id == project.id)
        ) or 0
        if count >= settings.max_competitors:
            raise AppError(409, "COMPETITOR_LIMIT", f"You can track up to {settings.max_competitors} competitors.")
        duplicate = session.scalar(
            select(Competitor).where(Competitor.project_id == project.id, func.lower(Competitor.name) == request.name.strip().lower())
        )
        if duplicate:
            raise AppError(409, "COMPETITOR_DUPLICATE", "This competitor is already tracked.")

        competitor = Competitor(
            project_id=project.id,
            name=request.name,
            website=str(request.website),
        )

        session.add(competitor)
        session.commit()
        session.refresh(competitor)

        return {
            "id": competitor.id,
            "name": competitor.name,
            "website": competitor.website,
        }


@router.get("")
def list_competitors(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:

        project = get_user_project(
            session,
            project_id,
            current_user.id,
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        competitors = session.scalars(
            select(Competitor).where(
                Competitor.project_id == project.id
            )
        ).all()

        return [
            {
                "id": competitor.id,
                "name": competitor.name,
                "website": competitor.website,
            }
            for competitor in competitors
        ]


@router.delete("/{competitor_id}")
def delete_competitor(
    project_id: UUID,
    competitor_id: int,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:

        project = get_user_project(
            session,
            project_id,
            current_user.id,
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        competitor = session.scalar(
            select(Competitor).where(
                Competitor.id == competitor_id,
                Competitor.project_id == project.id,
            )
        )

        if not competitor:
            raise HTTPException(
                status_code=404,
                detail="Competitor not found",
            )

        session.delete(competitor)
        session.commit()

        return {
            "message": "Competitor deleted successfully"
        }

@router.patch("/{competitor_id}")
def update_competitor(
    project_id: UUID,
    competitor_id: int,
    request: CompetitorUpdate,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_user_project(session, project_id, current_user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        competitor = session.scalar(
            select(Competitor).where(Competitor.id == competitor_id, Competitor.project_id == project.id)
        )
        if not competitor:
            raise HTTPException(status_code=404, detail="Competitor not found")
        if request.name is not None:
            competitor.name = request.name.strip()
        if request.website is not None:
            competitor.website = str(request.website)
        session.commit()
        session.refresh(competitor)
        return {"id": competitor.id, "name": competitor.name, "website": competitor.website}
