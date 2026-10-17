import httpx

from app.common.config import settings
from app.common.errors import AppError

RESEND_URL = "https://api.resend.com/emails"


def send_report_email(to: str, subject: str, html: str) -> None:
    if not settings.resend_api_key.strip():
        raise AppError(503, "EMAIL_NOT_CONFIGURED", "Email delivery is not configured.")
    try:
        response = httpx.post(
            RESEND_URL,
            json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise AppError(502, "EMAIL_SEND_FAILED", "Could not reach the email provider.") from exc
    if response.status_code >= 400:
        raise AppError(502, "EMAIL_SEND_FAILED", "The email provider rejected the message.")
