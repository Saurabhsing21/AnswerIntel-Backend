"""Data retention (PRD 88). Raw answers expire; the aggregates computed from them never do.

Each workspace keeps raw answers for its plan's retention (app/billing/plans.py); `raw_response_days` is
the ceiling for everyone. Deleting an answer cascades to its mentions, citations and competitor observations. Metric snapshots,
competitor metrics, opportunities, reports and experiment snapshots hold no reference to it, so history
keeps working after the raw text is gone.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select

from app.auth.models import RefreshToken
from app.billing.models import Subscription
from app.billing.plans import PLANS
from app.common.database import SessionLocal
from app.projects.models import Project
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan

TOKEN_GRACE_DAYS = 7


def purge_expired(now: datetime, raw_response_days: int, batch_size: int = 1000) -> dict:
    token_cutoff = now - timedelta(days=TOKEN_GRACE_DAYS)
    # (cutoff, extra condition): plans that keep less than the ceiling first, then the ceiling for everyone.
    passes = [
        (now - timedelta(days=plan.retention_days), AIResponseRecord.scan_id.in_(
            select(Scan.id).join(Project, Project.id == Scan.project_id)
            .join(Subscription, Subscription.workspace_id == Project.workspace_id)
            .where(Subscription.plan == plan.key)
        ))
        for plan in PLANS.values() if plan.retention_days < raw_response_days
    ] + [(now - timedelta(days=raw_response_days), None)]
    responses = tokens = 0
    with SessionLocal() as session:
        for cutoff, condition in passes:
            query = select(AIResponseRecord.id).where(AIResponseRecord.created_at < cutoff)
            if condition is not None:
                query = query.where(condition)
            while True:  # small batches keep locks short on a busy table
                ids = list(session.scalars(query.limit(batch_size)))
                if not ids:
                    break
                responses += session.execute(delete(AIResponseRecord).where(AIResponseRecord.id.in_(ids))).rowcount
                session.commit()
        tokens = session.execute(
            delete(RefreshToken).where(or_(RefreshToken.expires_at < token_cutoff, RefreshToken.revoked_at < token_cutoff))
        ).rowcount
        session.commit()
    return {"responses": responses, "refresh_tokens": tokens}
