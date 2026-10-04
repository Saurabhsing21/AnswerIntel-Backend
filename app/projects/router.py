from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.common.database import SessionLocal
from app.projects.models import Project
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
        project = Project(
            user_id=current_user.id,
            brand_name=request.brand_name,
            website=str(request.website),
            description=request.description,
            category=request.category,
            country=request.country,
        )

        session.add(project)
        session.commit()
        session.refresh(project)

        return {
            "id": str(project.id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
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
                Project.user_id == current_user.id,
            )
        )

        if not project:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        return {
            "id": str(project.id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
        }


@router.get("")
def list_projects(
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        projects = session.scalars(
            select(Project).where(
                Project.user_id == current_user.id
            )
        ).all()

        return [
            {
                "id": str(project.id),
                "brand_name": project.brand_name,
                "website": project.website,
                "description": project.description,
                "category": project.category,
                "country": project.country,
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
                Project.user_id == current_user.id,
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

        session.commit()
        session.refresh(project)

        return {
            "id": str(project.id),
            "brand_name": project.brand_name,
            "website": project.website,
            "description": project.description,
            "category": project.category,
            "country": project.country,
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
                Project.user_id == current_user.id,
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