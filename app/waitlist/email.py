"""The 'you're on the list' email. Sent once, when an address joins for the first time."""

import logging
from app.common.config import settings
from app.common.email_layout import email_html
from app.common.errors import AppError
from app.reports.email import send_report_email

log = logging.getLogger(__name__)

SUBJECT = "You're on the SeenLens waitlist"


def render(site: str) -> str:
    return email_html(
        heading="You're on the list.",
        paragraphs=[
            "Thanks for joining. SeenLens shows you when ChatGPT, Perplexity, Gemini and Google AI recommend your brand, "
            "when they pick a competitor instead, and what to fix.",
            "We're opening access in small groups. We'll email you as soon as your spot is ready, and your first scan is on us.",
        ],
        eyebrow="Waitlist",
        button=("Visit SeenLens", site),
        footer="You got this because this address joined the SeenLens waitlist.",
        preheader="Thanks for joining. We'll email you when your spot is ready.",
    )


def send_welcome(email: str) -> None:
    """Never raises: a failed email must not undo the signup. The address itself is not logged."""
    try:
        send_report_email(email, SUBJECT, render(settings.app_base_url))
    except AppError as exc:
        log.warning("Waitlist confirmation not sent: %s", exc.code)
