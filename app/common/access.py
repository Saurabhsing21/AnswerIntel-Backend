from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.projects.models import Project
from app.workspaces.models import WorkspaceMember


def project_access(user_id: int):
    """SQL condition: the project's workspace is one the user belongs to (PRD sections 7 and 64)."""
    return Project.workspace_id.in_(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id))


def get_owned_project(session: Session, project_id: UUID, user_id: int) -> Project:
    """Every customer-data query goes through workspace membership (PRD section 64)."""
    project = session.scalar(select(Project).where(Project.id == project_id, project_access(user_id)))
    if not project:
        raise AppError(404, "PROJECT_NOT_FOUND", "Project not found.")
    return project
