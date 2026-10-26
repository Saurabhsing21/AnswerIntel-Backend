import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import links
from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_pro, require_room
from app.billing import service as billing
from app.billing.service import seat_count
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceInvite, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

INVITE_DAYS = 14


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _send_invite(email: str, workspace_name: str, inviter: str, token: str | None) -> None:
    """`token` None: they already have an account and were added straight away."""
    if token:
        url, button = links.link("/invite", token), "Accept the invitation"
        footer = f"The invitation expires in {INVITE_DAYS} days. Sign up or log in with this email address to accept."
    else:
        url, button, footer = f"{settings.app_base_url.rstrip('/')}/projects", "Open SeenLens", "You can leave the workspace any time from Team."
    links.send(email, f"{inviter} invited you to {workspace_name} on SeenLens", links.render(
        f"Join {workspace_name} on SeenLens",
        f"{inviter} invited you to see how AI engines talk about their brand and competitors.",
        button, url, footer,
    ))


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["owner", "admin", "member"] = "member"


class RoleChange(BaseModel):
    role: Literal["owner", "admin", "member"]


class InviteAccept(BaseModel):
    token: str


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
        billing.open_billing(session, workspace.id)
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role="owner"))
        session.commit()
        return {"id": str(workspace.id), "name": workspace.name, "role": "owner"}


@router.get("/{workspace_id}/members")
def list_members(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_member(session, workspace_id, current_user)
        rows = session.execute(
            select(User.id, User.email, User.name, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at)
        ).all()
        return [{"user_id": uid, "email": email, "name": name, "role": role} for uid, email, name, role in rows]


@router.patch("/{workspace_id}")
def rename_workspace(workspace_id: UUID, payload: WorkspaceCreate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        member = _require_manager(session, workspace_id, current_user)
        workspace = session.get(Workspace, workspace_id)
        workspace.name = payload.name.strip()
        session.commit()
        return {"id": str(workspace.id), "name": workspace.name, "role": member.role}


@router.post("/{workspace_id}/members")
def add_member(workspace_id: UUID, payload: MemberAdd, background: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Adds an existing account straight away; anyone else gets an emailed invitation."""
    email = str(payload.email).lower()
    with SessionLocal() as session:
        actor = _require_manager(session, workspace_id, current_user)
        if payload.role == "owner" and actor.role != "owner":
            raise AppError(403, "FORBIDDEN", "Only an owner can grant ownership.")
        ent = entitlements(session, workspace_id)
        require_pro(ent, "Team invites")
        require_room(ent, "seats", seat_count(session, workspace_id), f"Your plan includes {ent.seats} seats.")
        workspace_name = session.scalar(select(Workspace.name).where(Workspace.id == workspace_id))
        inviter = current_user.name or current_user.email
        user = session.scalar(select(User).where(func.lower(User.email) == email))
        if user:
            if _membership(session, workspace_id, user.id):
                raise AppError(409, "ALREADY_MEMBER", "That person is already in this workspace.")
            session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=payload.role))
            session.commit()
            background.add_task(_send_invite, user.email, workspace_name, inviter, None)
            return {"user_id": user.id, "email": user.email, "role": payload.role, "invited": False}
        # One open invitation per address: inviting again replaces the old link.
        session.execute(delete(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id, func.lower(WorkspaceInvite.email) == email,
            WorkspaceInvite.accepted_at.is_(None),
        ))
        token = secrets.token_urlsafe(32)
        session.add(WorkspaceInvite(
            workspace_id=workspace_id, email=email, role=payload.role, token_hash=_hash(token), invited_by=current_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS),
        ))
        session.commit()
        background.add_task(_send_invite, email, workspace_name, inviter, token)
        return {"user_id": None, "email": email, "role": payload.role, "invited": True}


@router.get("/{workspace_id}/invites")
def list_invites(workspace_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_member(session, workspace_id, current_user)
        invites = session.scalars(
            select(WorkspaceInvite).where(
                WorkspaceInvite.workspace_id == workspace_id, WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.expires_at > datetime.now(timezone.utc),
            ).order_by(WorkspaceInvite.created_at)
        ).all()
        return [{"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at} for i in invites]


@router.delete("/{workspace_id}/invites/{invite_id}")
def cancel_invite(workspace_id: UUID, invite_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _require_manager(session, workspace_id, current_user)
        invite = session.get(WorkspaceInvite, invite_id)
        if not invite or invite.workspace_id != workspace_id or invite.accepted_at:
            raise AppError(404, "INVITE_NOT_FOUND", "Invitation not found.")
        session.delete(invite)
        session.commit()
        return {"ok": True}


@router.post("/invites/accept")
def accept_invite(payload: InviteAccept, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        invite = session.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token_hash == _hash(payload.token)))
        if not invite or invite.accepted_at or invite.expires_at <= datetime.now(timezone.utc):
            raise AppError(400, "INVITE_INVALID", "This invitation is invalid or has expired. Ask for a new one.")
        if invite.email.lower() != current_user.email.lower():
            raise AppError(403, "INVITE_WRONG_ACCOUNT", f"This invitation was sent to {invite.email}. Log in with that email to accept it.")
        if not _membership(session, invite.workspace_id, current_user.id):
            session.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=current_user.id, role=invite.role))
        invite.accepted_at = datetime.now(timezone.utc)
        user = session.get(User, current_user.id)
        user.email_verified_at = user.email_verified_at or invite.accepted_at  # the link reached this inbox
        workspace = session.get(Workspace, invite.workspace_id)
        session.commit()
        return {"id": str(workspace.id), "name": workspace.name, "role": invite.role}


@router.patch("/{workspace_id}/members/{user_id}")
def change_role(workspace_id: UUID, user_id: int, payload: RoleChange, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        actor = _require_manager(session, workspace_id, current_user)
        target = _membership(session, workspace_id, user_id)
        if not target:
            raise AppError(404, "MEMBER_NOT_FOUND", "That person is not in this workspace.")
        if "owner" in (payload.role, target.role) and actor.role != "owner":
            raise AppError(403, "FORBIDDEN", "Only an owner can grant or take away ownership.")
        if target.role == "owner" and payload.role != "owner" and _owner_count(session, workspace_id) <= 1:
            raise AppError(409, "LAST_OWNER", "A workspace must keep at least one owner.")
        target.role = payload.role
        session.commit()
        return {"user_id": user_id, "role": payload.role}


def _owner_count(session: Session, workspace_id: UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner"
        )
    )


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
