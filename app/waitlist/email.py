"""The 'you're on the list' email. Sent once, when an address joins for the first time."""

import logging
from html import escape

from app.common.config import settings
from app.common.errors import AppError
from app.reports.email import send_report_email

log = logging.getLogger(__name__)

SUBJECT = "You're on the SeenLens waitlist"


def render(site: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;background:#f7f7f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#171717">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border:1px solid #e5e5e5;border-radius:20px">
<tr><td style="padding:36px 36px 8px">
<p style="margin:0 0 24px;font-size:18px;font-weight:600">SeenLens</p>
<h1 style="margin:0 0 12px;font-size:26px;line-height:1.2;letter-spacing:-0.02em">You're on the list.</h1>
<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#404040">Thanks for joining. SeenLens shows you when ChatGPT, Perplexity, Gemini and Google AI recommend your brand, when they pick a competitor instead, and what to fix.</p>
<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#404040">We're opening access in small groups. We'll email you as soon as your spot is ready, and your first scan is on us.</p>
</td></tr>
<tr><td style="padding:8px 36px 36px">
<a href="{escape(site)}" style="display:inline-block;background:#171717;color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;padding:12px 20px;border-radius:999px">Visit SeenLens</a>
</td></tr>
</table>
<p style="margin:16px 0 0;font-size:12px;color:#a3a3a3">You got this because this address joined the SeenLens waitlist.</p>
</td></tr></table>
</body></html>"""


def send_welcome(email: str) -> None:
    """Never raises: a failed email must not undo the signup. The address itself is not logged."""
    try:
        send_report_email(email, SUBJECT, render(settings.app_base_url))
    except AppError as exc:
        log.warning("Waitlist confirmation not sent: %s", exc.code)
