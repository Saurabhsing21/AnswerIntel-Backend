from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["owner", "admin", "member"] = "member"


def _membership(session: Session, workspace_id: UUID, user_id: int) -> WorkspaceMember | None:
    return session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
    )


def _require_member(session: Session, workspace_id: UUID, user: User) -> WorkspaceMember:
    member = _membership(session, workspace_id, user.id)
    if not member:  # a workspace you are not in looks exactly like one that does not exist
        raise AppError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return member


def _require_manager(session: Session, workspace_id: UUID, user: User) -> WorkspaceMember:
    member = _require_member(session, workspace_id, user)
    if member.role not in ("owner", "admin"):
        raise AppError(403, "FORBIDDEN", "Only workspace owners and admins can do that.")
    return member


@router.get("")
def list_workspaces(current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        rows = session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == current_user.id)
            .order_by(WorkspaceMember.created_at, Workspace.name)
        ).all()
        return [{"id": str(w.id), "name": w.name, "role": role} for w, role in rows]


@router.post("")
def create_workspace(payload: WorkspaceCreate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        workspace = Workspace(name=payload.name.strip())
        session.add(workspace)
        session.flush()
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role="owner"))
        session.commit()
        return {"id": str(workspace.id), "name": workspace.name, "role": "owner"}


@router.get("/{workspace_id}/members")
def list_members(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_member(session, workspace_id, current_user)
        rows = session.execute(
            select(User.id, User.email, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at)
        ).all()
        return [{"user_id": uid, "email": email, "role": role} for uid, email, role in rows]


@router.post("/{workspace_id}/members")
def add_member(workspace_id: UUID, payload: MemberAdd, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        actor = _require_manager(session, workspace_id, current_user)
        if payload.role == "owner" and actor.role != "owner":
            raise AppError(403, "FORBIDDEN", "Only an owner can grant ownership.")
        # Adds an existing account. Email invitations for people without an account are not built yet.
        user = session.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower()))
        if not user:
            raise AppError(404, "USER_NOT_FOUND", "No SeenLens account exists for that email.")
        if _membership(session, workspace_id, user.id):
            raise AppError(409, "ALREADY_MEMBER", "That person is already in this workspace.")
        session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=payload.role))
        session.commit()
        return {"user_id": user.id, "email": user.email, "role": payload.role}


@router.delete("/{workspace_id}/members/{user_id}")
def remove_member(workspace_id: UUID, user_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        actor = _require_member(session, workspace_id, current_user)
        target = _membership(session, workspace_id, user_id)
        if not target:
            raise AppError(404, "MEMBER_NOT_FOUND", "That person is not in this workspace.")
        if user_id != current_user.id:  # leaving yourself is always allowed; removing others needs a manager
            if actor.role not in ("owner", "admin"):
                raise AppError(403, "FORBIDDEN", "Only workspace owners and admins can remove people.")
            if target.role == "owner" and actor.role != "owner":
                raise AppError(403, "FORBIDDEN", "Only an owner can remove an owner.")
        if target.role == "owner":
            owners = session.scalar(
                select(func.count()).select_from(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner"
                )
            )
            if owners <= 1:
                raise AppError(409, "LAST_OWNER", "A workspace must keep at least one owner.")
        session.delete(target)
        session.commit()
        return {"ok": True}
