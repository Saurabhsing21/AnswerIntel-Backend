"""Data retention (PRD 88). Raw answers expire; the aggregates computed from them never do.

Deleting an answer cascades to its mentions, citations and competitor observations. Metric snapshots,
competitor metrics, opportunities, reports and experiment snapshots hold no reference to it, so history
keeps working after the raw text is gone.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select

from app.auth.models import RefreshToken
from app.common.database import SessionLocal
from app.providers.response_model import AIResponseRecord

TOKEN_GRACE_DAYS = 7


def purge_expired(now: datetime, raw_response_days: int, batch_size: int = 1000) -> dict:
    cutoff = now - timedelta(days=raw_response_days)
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)
    responses = tokens = 0
    with SessionLocal() as session:
        while True:  # small batches keep locks short on a busy table
            ids = list(session.scalars(select(AIResponseRecord.id).where(AIResponseRecord.created_at < cutoff).limit(batch_size)))
            if not ids:
                break
            responses += session.execute(delete(AIResponseRecord).where(AIResponseRecord.id.in_(ids))).rowcount
            session.commit()
        tokens = session.execute(
            delete(RefreshToken).where(or_(RefreshToken.expires_at < token_cutoff, RefreshToken.revoked_at < token_cutoff))
        ).rowcount
        session.commit()
    return {"responses": responses, "refresh_tokens": tokens}
