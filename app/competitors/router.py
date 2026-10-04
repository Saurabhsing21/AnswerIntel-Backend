from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from app.competitors.schemas import CompetitorCreate
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
            Project.user_id == user_id,
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