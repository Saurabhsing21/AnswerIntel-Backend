"""Billing emails: payment failed, and trial ending/ended for workspaces that predate billing. Sent to the owners."""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from app.billing.models import Subscription
from app.common.config import settings
from app.common.email_layout import email_html
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.reports.email import send_report_email
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember

log = logging.getLogger(__name__)


def notify_owners(
    session, workspace_id: UUID, subject: str, body: str, *, path: str = "/projects", button: str = "Open SeenLens",
    stats: list[tuple[str, str]] | None = None, items: list[str] | None = None,
) -> int:
    """Returns how many owners were emailed. Email being off or failing never breaks billing."""
    name = session.scalar(select(Workspace.name).where(Workspace.id == workspace_id)) or "Your workspace"
    emails = session.scalars(
        select(User.email).join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
    ).all()
    sent = 0
    for email in emails:
        try:
            send_report_email(email, subject, email_html(
                heading=subject, paragraphs=[body], eyebrow=name, stats=stats, items=items, preheader=body,
                button=(button, f"{settings.app_base_url.rstrip('/')}{path}"),
                footer=f"You get this because you own {name} on SeenLens.",
            ))
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


# Free-trial follow-ups, one step a day apart at most: (notice, days after signup). Stops once they pay.
FREE_STEPS = (("free_day1", 1), ("free_day3", 3), ("free_day7", 7))


def _free_email(step: str, scanned: bool) -> tuple[str, str]:
    if step == "free_day1":
        if not scanned:
            return "Your free AI visibility scan is waiting", (
                "Add your website and we'll ask ChatGPT, Perplexity and Gemini the questions your buyers ask, then show "
                "where they recommend you and who they pick instead. It takes about two minutes."
            )
        return "Start with the top fix from your scan", (
            "Your scan found the questions where AI recommends a competitor instead of you. Open Opportunities: each one "
            "has concrete steps, and you can re-test the questions after you ship the fix."
        )
    if step == "free_day3":
        return "AI answers change every week", (
            "One scan is a snapshot. On a plan, SeenLens re-asks every question weekly, emails you when a competitor "
            "overtakes you, and proves which fixes worked. Plans start at $20 a month."
        )
    return "Keep tracking your AI visibility", (
        "Your free scan and its results are still here. Choose a plan to track them weekly and see whether your "
        "changes move the numbers."
    )


def send_free_nudges(now: datetime) -> dict:
    """Daily job. A free workspace gets each follow-up once, in order, while it stays on the free trial."""
    from app.billing.service import scans_ever

    sent = {step: 0 for step, _ in FREE_STEPS}
    order = [step for step, _ in FREE_STEPS]
    with SessionLocal() as session:
        for sub in session.scalars(select(Subscription).where(Subscription.plan == "free")).all():
            done = order.index(sub.notified) + 1 if sub.notified in order else 0
            if done == len(order):
                continue
            step, days = FREE_STEPS[done]
            if sub.created_at > now - timedelta(days=days):
                continue
            subject, body = _free_email(step, scans_ever(session, sub.workspace_id) > 0)
            notify_owners(session, sub.workspace_id, subject, body)
            sub.notified = step
            sent[step] += 1
            session.commit()
    return sent
