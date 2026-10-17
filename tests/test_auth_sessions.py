"""PRD section 6: short-lived access token, rotating refresh token, logout, theft detection."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.auth.models import RefreshToken
from app.common.database import SessionLocal
from app.users.models import User
from tests.conftest import API


def register_and_login(client) -> tuple[str, dict]:
    email = f"sess-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    login = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    return email, login.json()


def refresh(client, token: str):
    return client.post(f"{API}/auth/refresh", json={"refresh_token": token})


def test_login_issues_both_tokens(client):
    _, tokens = register_and_login(client)
    assert tokens["token_type"] == "bearer" and tokens["access_token"] and tokens["refresh_token"]
    assert tokens["expires_in"] > 0
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200


def test_refresh_rotates_the_token_pair(client):
    _, tokens = register_and_login(client)
    renewed = refresh(client, tokens["refresh_token"])
    assert renewed.status_code == 200
    new = renewed.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert me.status_code == 200


def test_replaying_a_used_refresh_token_signs_the_user_out_everywhere(client):
    _, tokens = register_and_login(client)
    newer = refresh(client, tokens["refresh_token"]).json()

    replay = refresh(client, tokens["refresh_token"])  # someone is replaying a stolen, already-used token
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "AUTH_INVALID_REFRESH_TOKEN"
    assert refresh(client, newer["refresh_token"]).status_code == 401  # the legitimate chain is revoked too


def test_logout_revokes_the_refresh_token(client):
    _, tokens = register_and_login(client)
    assert client.post(f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]}).json() == {"ok": True}
    assert refresh(client, tokens["refresh_token"]).status_code == 401
    # Logging out is idempotent and never reveals whether a token existed.
    assert client.post(f"{API}/auth/logout", json={"refresh_token": "garbage"}).json() == {"ok": True}


def test_expired_and_unknown_refresh_tokens_are_rejected(client):
    email, tokens = register_and_login(client)
    assert refresh(client, "never-issued").status_code == 401
    with SessionLocal() as session:
        user_id = session.scalar(select(User.id).where(User.email == email))
        session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user_id).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        session.commit()
    assert refresh(client, tokens["refresh_token"]).status_code == 401


def test_deactivated_users_cannot_refresh(client):
    email, tokens = register_and_login(client)
    with SessionLocal() as session:
        session.execute(update(User).where(User.email == email).values(is_active=False))
        session.commit()
    assert refresh(client, tokens["refresh_token"]).status_code == 401


def test_refresh_tokens_are_stored_hashed(client):
    email, tokens = register_and_login(client)
    with SessionLocal() as session:
        user_id = session.scalar(select(User.id).where(User.email == email))
        stored = session.scalars(select(RefreshToken.token_hash).where(RefreshToken.user_id == user_id)).all()
    assert stored and tokens["refresh_token"] not in stored
    assert all(len(value) == 64 for value in stored)  # sha-256 hex digests
