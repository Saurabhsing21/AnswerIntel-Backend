import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, update
from sqlalchemy import select

from app.auth.password import hash_password
from app.auth.schemas import RegisterRequest
from app.common.database import SessionLocal
from app.users.models import User
from app.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest
from app.auth.password import hash_password, verify_password
from app.auth import google, links
from app.auth.models import RefreshToken
from app.auth.refresh import issue_tokens, revoke, rotate
from app.common.errors import AppError
from fastapi import Depends
from app.auth.dependencies import get_current_user
from app.common.ratelimit import limit_login
from app.workspaces.models import Workspace, WorkspaceMember
from app.billing import service as billing


router = APIRouter(prefix="/auth", tags=["Auth"])


def _create_account(session, email: str, password_hash: str, verified: bool = False) -> User:
    """A new user and their own workspace (PRD 7), which starts on the free trial. The caller commits."""
    user = User(email=email, password_hash=password_hash, email_verified_at=datetime.now(timezone.utc) if verified else None)
    session.add(user)
    session.flush()
    workspace = Workspace(name=f"{email.split('@')[0]}'s workspace")
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    billing.open_billing(session, workspace.id, trial=True)
    return user


@router.post("/register")
def register(request: RegisterRequest, background: BackgroundTasks):
    with SessionLocal() as session:
        existing_user = session.scalar(
            select(User).where(User.email == request.email)
        )

        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )

        user = _create_account(session, request.email, hash_password(request.password))
        session.commit()
        session.refresh(user)
        background.add_task(links.send_verification, user)

        return {
            "id": user.id,
            "email": user.email,
        }



@router.post("/login", dependencies=[Depends(limit_login)])
def login(request: LoginRequest):
    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(User.email == request.email)
        )

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        if not verify_password(
            request.password,
            user.password_hash,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        tokens = issue_tokens(session, user)
        session.commit()
        return tokens


class GoogleLogin(BaseModel):
    credential: str


@router.post("/google", dependencies=[Depends(limit_login)])
def google_login(payload: GoogleLogin):
    """Log in, or create the account on first use. Google has already confirmed the email address."""
    email = google.verified_email(payload.credential)
    if not email:
        raise AppError(401, "GOOGLE_LOGIN_FAILED", "Google sign-in didn't work. Please try again.")
    with SessionLocal() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            # No password yet: they can set one any time with "Forgot your password?".
            user = _create_account(session, email, hash_password(secrets.token_urlsafe(32)), verified=True)
        elif not user.is_active:
            raise AppError(401, "GOOGLE_LOGIN_FAILED", "Google sign-in didn't work. Please try again.")
        else:
            user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
        tokens = issue_tokens(session, user)
        session.commit()
        return tokens


@router.post("/refresh")
def refresh(request: RefreshRequest):
    with SessionLocal() as session:
        return rotate(session, request.refresh_token)


@router.post("/logout")
def logout(request: RefreshRequest):
    with SessionLocal() as session:
        revoke(session, request.refresh_token)
        return {"ok": True}

def _me(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "email_verified": user.email_verified_at is not None}


def _revoke_all(session, user_id: int) -> None:
    session.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def _bad_link() -> AppError:
    return AppError(400, "LINK_INVALID", "This link is invalid or has expired. Ask for a new one.")


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return _me(current_user)


class ProfileUpdate(BaseModel):
    name: str = Field(max_length=100)


@router.patch("/me")
def update_me(payload: ProfileUpdate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        user = session.get(User, current_user.id)
        user.name = payload.name.strip() or None
        session.commit()
        return _me(user)


class ForgotPassword(BaseModel):
    email: EmailStr


@router.post("/forgot-password", dependencies=[Depends(limit_login)])
def forgot_password(payload: ForgotPassword, background: BackgroundTasks):
    """Always the same answer, so the form can't be used to find out who has an account."""
    with SessionLocal() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower()))
        if user and user.is_active:
            session.expunge(user)
            background.add_task(links.send_reset, user)
    return {"ok": True}


class ResetPassword(BaseModel):
    token: str
    password: str = Field(min_length=8)


@router.post("/reset-password", dependencies=[Depends(limit_login)])
def reset_password(payload: ResetPassword):
    with SessionLocal() as session:
        try:
            user = links.read_reset_token(payload.token, lambda uid: session.get(User, uid))
        except ValueError:
            raise _bad_link()
        user.password_hash = hash_password(payload.password)
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)  # they read mail sent to it
        _revoke_all(session, user.id)  # anyone signed in with the old password is signed out
        session.commit()
        return {"ok": True, "email": user.email}


class VerifyEmail(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(payload: VerifyEmail):
    try:
        user_id, email = links.read_verify_token(payload.token)
    except ValueError:
        raise _bad_link()
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if not user or not user.is_active:
            raise _bad_link()
        if email.lower() != user.email.lower():
            taken = session.scalar(select(User.id).where(func.lower(User.email) == email.lower(), User.id != user.id))
            if taken:
                raise AppError(409, "EMAIL_TAKEN", "Another account already uses that email.")
            user.email = email
        user.email_verified_at = datetime.now(timezone.utc)
        session.commit()
        return {"ok": True, "email": user.email}


@router.post("/send-verification")
def send_verification(background: BackgroundTasks, current_user: User = Depends(get_current_user)):
    if current_user.email_verified_at is None:
        background.add_task(links.send_verification, current_user)
    return {"ok": True}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/change-password")
def change_password(payload: ChangePassword, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        user = session.get(User, current_user.id)
        if not verify_password(payload.current_password, user.password_hash):
            raise AppError(400, "WRONG_PASSWORD", "Your current password is not right.")
        user.password_hash = hash_password(payload.new_password)
        _revoke_all(session, user.id)  # every other device signs in again; this one logs in with the new password
        session.commit()
        return {"ok": True}


class ChangeEmail(BaseModel):
    new_email: EmailStr
    password: str


@router.post("/change-email")
def change_email(payload: ChangeEmail, background: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """The login email changes only when the link sent to the new address is clicked."""
    if not verify_password(payload.password, current_user.password_hash):
        raise AppError(400, "WRONG_PASSWORD", "Your password is not right.")
    new_email = str(payload.new_email)
    with SessionLocal() as session:
        if session.scalar(select(User.id).where(func.lower(User.email) == new_email.lower(), User.id != current_user.id)):
            raise AppError(409, "EMAIL_TAKEN", "Another account already uses that email.")
    background.add_task(links.send_verification, current_user, new_email)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        _revoke_all(session, current_user.id)
        session.commit()
    return {"ok": True}