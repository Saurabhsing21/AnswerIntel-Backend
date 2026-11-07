"""Refresh-token sessions (PRD 6): rotate on every use, revoke everything if a used token is replayed."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.models import RefreshToken
from app.common.config import settings
from app.common.errors import AppError
from app.users.models import User

# Several requests that hit an expired access token at once (often on different servers) all refresh with the
# same token. Within this window the losers of that race get their own new pair instead of a theft alarm.
REUSE_GRACE = timedelta(seconds=30)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _invalid() -> AppError:
    return AppError(401, "AUTH_INVALID_REFRESH_TOKEN", "Your session has expired. Please sign in again.")


def _issue(session: Session, user: User) -> tuple[dict, RefreshToken]:
    refresh_token = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user.id,
        token_hash=_hash(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(row)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "refresh_token": refresh_token,
    }, row


def issue_tokens(session: Session, user: User) -> dict:
    """Create an access token and a new refresh token. The caller commits."""
    return _issue(session, user)[0]


def _raced_rotation(session: Session, stored: RefreshToken, now: datetime) -> bool:
    """Rotated moments ago and its replacement is still live: a parallel request, not a replayed stolen token.
    A logged-out token has no replacement, and a theft alarm revokes the replacement, so neither qualifies."""
    if stored.replaced_by_id is None or now - stored.revoked_at > REUSE_GRACE:
        return False
    successor = session.get(RefreshToken, stored.replaced_by_id)
    return successor is not None and successor.revoked_at is None


def rotate(session: Session, refresh_token: str) -> dict:
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(refresh_token)))
    now = datetime.now(timezone.utc)
    if not stored:
        raise _invalid()
    if stored.revoked_at is not None and not _raced_rotation(session, stored, now):
        # An already-used token is being replayed: assume theft and end every session for this user.
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        session.commit()
        raise _invalid()
    user = session.get(User, stored.user_id)
    if stored.expires_at <= now or not user or not user.is_active:
        raise _invalid()
    if stored.revoked_at is not None:  # lost a rotation race: a new pair of its own, the winner's stays valid
        tokens = issue_tokens(session, user)
        session.commit()
        return tokens
    tokens, successor = _issue(session, user)
    session.flush()
    stored.revoked_at = now
    stored.replaced_by_id = successor.id
    session.commit()
    return tokens


def revoke(session: Session, refresh_token: str) -> None:
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(refresh_token)))
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        session.commit()
