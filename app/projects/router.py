from app.providers.models import engines_for_project
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing.plans import check_engine_choice, engines_for, entitlements, require_room
from app.billing.service import project_count
from app.common.access import project_access
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.projects.models import Project
from app.schedules.models import ScanSchedule
from app.workspaces.models import WorkspaceMember
from app.projects.schemas import ProjectCreate, ProjectUpdate
from app.users.models import User


router = APIRouter(
    prefix="/projects",
    tags=["Projects"],
)


@router.post("")
def create_project(
    request: ProjectCreate,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        # Omitted workspace = the earliest one the user belongs to, i.e. their personal workspace.
        memberships = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == current_user.id)
        if request.workspace_id:
            memberships = memberships.where(WorkspaceMember.workspace_id == request.workspace_id)
        workspace_id = session.scalar(memberships.order_by(WorkspaceMember.created_at).limit(1))
        if not workspace_id:
            raise AppError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
        ent = entitlements(session, workspace_id)
        require_room(ent, "projects", project_count(session, workspace_id), f"Your plan includes {ent.projects} project(s).")
        if request.engines is not None:
            check_engine_choice(ent, request.engines)
        elif ent.locked_engines or ent.engines is not None:  # the free trial starts on engines it can actually use
            request.engines = [e.key for e in engines_for(engines_for_project(None), ent)]

        project = Project(
            workspace_id=workspace_id,
            user_id=current_user.id,
            brand_name=request.brand_name,
            website=str(request.website),
            description=request.description,
            category=request.category,
            country=request.country,
            engines=request.engines,
        )

        session.add(project)
        session.flush()
        # Every plan includes weekly tracking, so it starts switched on: same weekday and hour, from next week.
        now = datetime.now(timezone.utc)
        session.add(ScanSchedule(project_id=project.id, enabled=ent.schedules, day_of_week=now.weekday(), hour=now.hour, starts_at=now))
        session.commit()
        session.refresh(project)

        return {
            "id": str(project.id),
            "workspace_id": str(project.workspace_id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
            "engines": [e.key for e in engines_for_project(project.engines)],
        }


@router.get("/{project_id}")
def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = session.scalar(
            select(Project).where(
                Project.id == project_id,
                project_access(current_user.id),
            )
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        return {
            "id": str(project.id),
            "workspace_id": str(project.workspace_id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
            "engines": [e.key for e in engines_for_project(project.engines)],
        }


@router.get("")
def list_projects(
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        projects = session.scalars(
            select(Project).where(
                project_access(current_user.id)
            )
        ).all()

        return [
            {
                "id": str(project.id),
                "workspace_id": str(project.workspace_id),
                "brand_name": project.brand_name,
                "website": project.website,
                "description": project.description,
                "category": project.category,
                "country": project.country,
                "engines": [e.key for e in engines_for_project(project.engines)],
            }
            for project in projects
        ]

@router.put("/{project_id}")
def update_project(
    project_id: UUID,
    request: ProjectUpdate,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = session.scalar(
            select(Project).where(
                Project.id == project_id,
                project_access(current_user.id),
            )
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        if request.brand_name is not None:
            project.brand_name = request.brand_name

        if request.website is not None:
            project.website = str(request.website)

        if request.description is not None:
            project.description = request.description

        if request.category is not None:
            project.category = request.category

        if request.country is not None:
            project.country = request.country

        if request.engines is not None:
            check_engine_choice(entitlements(session, project.workspace_id), request.engines)
            project.engines = request.engines

        session.commit()
        session.refresh(project)

        return {
            "id": str(project.id),
            "workspace_id": str(project.workspace_id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
            "engines": [e.key for e in engines_for_project(project.engines)],
        }

@router.delete("/{project_id}")
def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = session.scalar(
            select(Project).where(
                Project.id == project_id,
                project_access(current_user.id),
            )
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        session.delete(project)
        session.commit()

        return {
            "message": "Project deleted successfully"
        }