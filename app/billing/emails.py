"""Billing emails: payment failed, and trial ending/ended for workspaces that predate billing. Sent to the owners."""

import logging
from datetime import datetime, timedelta
from html import escape
from uuid import UUID

from sqlalchemy import or_, select

from app.billing.models import Subscription
from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.reports.email import send_report_email
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember

log = logging.getLogger(__name__)


def _render(heading: str, body: str) -> str:
    link = f"{settings.app_base_url.rstrip('/')}/projects"
    return (
        '<!doctype html><html><body style="font-family:system-ui,sans-serif;color:#111;max-width:560px">'
        f"<h2>{escape(heading)}</h2><p>{escape(body)}</p>"
        f'<p><a href="{escape(link)}">Open SeenLens billing</a></p></body></html>'
    )


def notify_owners(session, workspace_id: UUID, subject: str, body: str) -> int:
    """Returns how many owners were emailed. Email being off or failing never breaks billing."""
    name = session.scalar(select(Workspace.name).where(Workspace.id == workspace_id)) or "Your workspace"
    emails = session.scalars(
        select(User.email).join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
    ).all()
    sent = 0
    for email in emails:
        try:
            send_report_email(email, subject, _render(f"{name}: {subject}", body))
            sent += 1
        except AppError as exc:
            log.info("Billing email for workspace %s not sent: %s", workspace_id, exc.code)
    return sent


def send_payment_failed(workspace_id: UUID, grace_ends_at: datetime | None) -> None:
    when = f" by {grace_ends_at:%B %d}" if grace_ends_at else ""
    with SessionLocal() as session:
        notify_owners(
            session, workspace_id, "Your payment failed",
            f"We could not charge your card for SeenLens. Update your payment method{when} to keep scanning; "
            "after that the workspace becomes read-only.",
        )


def send_trial_notices(now: datetime) -> dict:
    """Daily job. Each trial gets at most one "ending soon" and one "ended" email (tracked in `notified`)."""
    counts = {"trial_ending": 0, "trial_ended": 0}
    with SessionLocal() as session:
        trials = session.scalars(
            select(Subscription).where(
                Subscription.plan == "trial",
                Subscription.trial_ends_at <= now + timedelta(days=3),
                or_(Subscription.notified.is_(None), Subscription.notified != "trial_ended"),
            )
        ).all()
        for sub in trials:
            if sub.trial_ends_at <= now:
                notice, subject, body = "trial_ended", "Your trial has ended", (
                    "Your SeenLens trial is over. Your data is still here and you can view and export it. "
                    "Choose a plan to start scanning again."
                )
            elif sub.notified is None:
                notice, subject, body = "trial_ending", "Your trial ends in 3 days", (
                    f"Your SeenLens trial ends on {sub.trial_ends_at:%B %d}. Choose a plan to keep your scans running."
                )
            else:
                continue
            notify_owners(session, sub.workspace_id, subject, body)
            sub.notified = notice
            counts[notice] += 1
            session.commit()
    return counts
