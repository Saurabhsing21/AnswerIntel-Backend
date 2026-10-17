"""PRD section 88: raw responses expire after 12 months; analytical aggregates never do."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.analysis.models import Mention
from app.auth.models import RefreshToken
from app.common.database import SessionLocal
from app.metrics.models import MetricSnapshot
from app.providers.response_model import AIResponseRecord
from app.scans.retention import purge_expired
from app.users.models import User
from tests.conftest import API, make_project, signup


def count(session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def scanned_project(client, prefix):
    headers = signup(client, prefix)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    return headers, project_id, scan["id"]


def test_old_raw_responses_are_purged_but_aggregates_survive(client):
    headers, project_id, old_scan = scanned_project(client, "retold")
    _, _, recent_scan = scanned_project(client, "retnew")
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    with SessionLocal() as session:
        session.execute(update(AIResponseRecord).where(AIResponseRecord.scan_id == old_scan).values(created_at=long_ago))
        session.commit()

    result = purge_expired(datetime.now(timezone.utc), raw_response_days=365)
    assert result["responses"] >= 1

    with SessionLocal() as session:
        assert count(session, AIResponseRecord, AIResponseRecord.scan_id == old_scan) == 0
        assert count(session, AIResponseRecord, AIResponseRecord.scan_id == recent_scan) > 0  # inside the window
        assert count(session, MetricSnapshot, MetricSnapshot.scan_id == old_scan) == 1  # aggregate is kept
        orphans = count(session, Mention, Mention.ai_response_id.notin_(select(AIResponseRecord.id)))
        assert orphans == 0  # per-answer analysis goes with its answer

    dashboard = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()
    assert dashboard["has_data"] is True and dashboard["visibility"]["total_responses"] > 0


def test_purge_works_in_small_batches(client):
    _, _, scan_id = scanned_project(client, "retbatch")
    with SessionLocal() as session:
        session.execute(update(AIResponseRecord).where(AIResponseRecord.scan_id == scan_id).values(created_at=datetime.now(timezone.utc) - timedelta(days=500)))
        session.commit()
        total = count(session, AIResponseRecord, AIResponseRecord.scan_id == scan_id)
    assert total > 2
    assert purge_expired(datetime.now(timezone.utc), raw_response_days=365, batch_size=2)["responses"] >= total
    with SessionLocal() as session:
        assert count(session, AIResponseRecord, AIResponseRecord.scan_id == scan_id) == 0


def test_dead_refresh_tokens_are_cleaned_up_active_ones_kept(client):
    email = f"tok-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    for _ in range(3):  # three logins -> three tokens
        client.post(f"{API}/auth/login", json={"email": email, "password": "password123"})
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        user_id = session.scalar(select(User.id).where(User.email == email))
        tokens = session.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id).order_by(RefreshToken.id)).all()
        tokens[0].expires_at = now - timedelta(days=30)  # long expired
        tokens[1].revoked_at = now - timedelta(days=30)  # long revoked
        session.commit()
        keep_id = tokens[2].id

    assert purge_expired(now, raw_response_days=365)["refresh_tokens"] >= 2
    with SessionLocal() as session:
        remaining = session.scalars(select(RefreshToken.id).where(RefreshToken.user_id == user_id)).all()
    assert remaining == [keep_id]
