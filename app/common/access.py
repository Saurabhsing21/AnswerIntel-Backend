from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.projects.models import Project


def get_owned_project(session: Session, project_id: UUID, user_id: int) -> Project:
    """Every customer-data query goes through ownership (PRD section 64)."""
    project = session.scalar(select(Project).where(Project.id == project_id, Project.user_id == user_id))
    if not project:
        raise AppError(404, "PROJECT_NOT_FOUND", "Project not found.")
    return project
