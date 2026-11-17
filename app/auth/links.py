"""Signed, expiring links emailed to people: password reset and email verification.

A reset link is bound to the current password hash, so it stops working once it has been used. A verification
link names the address it proves, so it also confirms a change of email.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError

from app.common.config import settings
from app.common.email_layout import email_html
from app.reports.email import send_report_email
from app.users.models import User

log = logging.getLogger(__name__)

RESET_MINUTES = 60
VERIFY_DAYS = 3
SIGNUP_MINUTES = 15


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def _sign(payload: dict, expires: timedelta) -> str:
    payload = {**payload, "exp": datetime.now(timezone.utc) + expires}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _read(token: str, purpose: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise ValueError("invalid link") from exc
    if payload.get("purpose") != purpose:
        raise ValueError("invalid link")
    return payload


def reset_token(user: User) -> str:
    return _sign({"purpose": "reset", "sub": str(user.id), "pw": _fingerprint(user.password_hash)}, timedelta(minutes=RESET_MINUTES))


def read_reset_token(token: str, load_user) -> User:
    payload = _read(token, "reset")
    user = load_user(int(payload["sub"]))
    if not user or not user.is_active or payload.get("pw") != _fingerprint(user.password_hash):
        raise ValueError("invalid link")
    return user


def verify_token(user: User, email: str) -> str:
    return _sign({"purpose": "verify", "sub": str(user.id), "email": email}, timedelta(days=VERIFY_DAYS))


def read_verify_token(token: str) -> tuple[int, str]:
    payload = _read(token, "verify")
    return int(payload["sub"]), payload["email"]


def _code_digest(email: str, code: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def signup_token(email: str, password_hash: str) -> tuple[str, str]:
    """A 6-digit code to email, and a token holding the pending signup. The account is made only once the code is
    entered, so nobody can open an account on an address they can't read."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = _sign({"purpose": "signup", "email": email, "pw": password_hash, "code": _code_digest(email, code)},
                  timedelta(minutes=SIGNUP_MINUTES))
    return token, code


def read_signup_token(token: str, code: str) -> tuple[str, str]:
    payload = _read(token, "signup")
    if not hmac.compare_digest(payload["code"], _code_digest(payload["email"], code.strip())):
        raise ValueError("wrong code")
    return payload["email"], payload["pw"]


def link(path: str, token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{path}?token={token}"


def render(heading: str, body: str, button: str, url: str, footer: str) -> str:
    return email_html(heading=heading, paragraphs=[body], button=(button, url), footer=footer, preheader=body)


def send(to: str, subject: str, html: str) -> None:
    """Best effort: a missing or failing email provider must never break the request that triggered it."""
    try:
        send_report_email(to, subject, html)
    except Exception:
        log.warning("Could not send %r email", subject, exc_info=True)


def send_reset(user: User) -> None:
    url = link("/reset-password", reset_token(user))
    send(user.email, "Reset your Seenlense password", render(
        "Reset your password", "Someone asked to reset the password for this Seenlense account.",
        "Choose a new password", url, f"The link works once and expires in {RESET_MINUTES} minutes. If this wasn't you, ignore this email.",
    ))


def send_verification(user: User, email: str | None = None) -> None:
    target = email or user.email
    url = link("/verify-email", verify_token(user, target))
    changing = target.lower() != user.email.lower()
    send(target, "Confirm your email for Seenlense", render(
        "Confirm your email",
        "Confirm this is your new Seenlense login email." if changing else "Confirm your email so we can send your reports and alerts.",
        "Confirm email", url, f"The link expires in {VERIFY_DAYS} days. If you didn't sign up for Seenlense, ignore this email.",
    ))


def send_signup_code(email: str, code: str) -> None:
    send(email, f"{code} is your SeenLense code", email_html(
        heading="Confirm your email",
        paragraphs=["Enter this code to finish creating your SeenLense account."],
        stats=[(code, "Sign-up code")],
        footer=f"The code expires in {SIGNUP_MINUTES} minutes. If you didn't sign up for SeenLense, ignore this email.",
        preheader=f"Your sign-up code is {code}",
    ))
