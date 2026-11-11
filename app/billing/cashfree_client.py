"""The only module that talks to Cashfree. Tests replace these functions; nothing else calls the Cashfree API."""

import base64
import calendar
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone

import httpx

from app.common.config import settings
from app.common.errors import AppError

log = logging.getLogger(__name__)

API_VERSION = "2025-01-01"
# Plan ids carry the price, so a price change in plans.py creates a new Cashfree plan and never edits a live one.
PLAN_ID = re.compile(r"^seenlense_(starter|growth|pro)_(month|year)_")

_known_plans: set[str] = set()


def _base() -> str:
    return "https://api.cashfree.com/pg" if settings.cashfree_env == "production" else "https://sandbox.cashfree.com/pg"


def _request(method: str, path: str, body: dict | None = None, missing_ok: bool = False) -> dict | None:
    if not settings.billing_enabled:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    headers = {
        "x-api-version": API_VERSION,
        "x-client-id": settings.cashfree_client_id,
        "x-client-secret": settings.cashfree_client_secret,
    }
    try:
        response = httpx.request(method, _base() + path, json=body, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        raise AppError(502, "BILLING_PROVIDER_ERROR", "Could not reach the payment provider. Please try again.") from exc
    if response.status_code >= 400:
        error = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        # Cashfree answers a missing plan or subscription with 400 and a *_not_found code, not 404.
        if missing_ok and (response.status_code == 404 or str(error.get("code", "")).endswith("not_found")):
            return None
        log.warning("Cashfree %s %s refused (%s): %s", method, path, response.status_code, error.get("message") or response.text[:200])
        raise AppError(502, "BILLING_PROVIDER_ERROR", "The payment provider refused the request. Please try again.")
    return response.json()


def plan_id(plan: str, interval: str, amount: int) -> str:
    return f"seenlense_{plan}_{interval}_{settings.cashfree_currency.lower()}{amount}"


def plan_of(cashfree_plan_id: str | None) -> tuple[str, str] | None:
    """(plan, interval) for one of our Cashfree plan ids, None for anything else."""
    match = PLAN_ID.match(cashfree_plan_id or "")
    return (match[1], match[2]) if match else None


def ensure_plan(plan: str, interval: str, name: str, amount: int) -> str:
    """Creates the Cashfree plan the first time it is needed and returns its id."""
    pid = plan_id(plan, interval, amount)
    if pid in _known_plans or _request("GET", f"/plans/{pid}", missing_ok=True):
        _known_plans.add(pid)
        return pid
    _request("POST", "/plans", {
        "plan_id": pid,
        "plan_name": f"SeenLense {name} {'yearly' if interval == 'year' else 'monthly'}",  # no brackets: Cashfree refuses them
        "plan_type": "PERIODIC",
        "plan_currency": settings.cashfree_currency,
        "plan_recurring_amount": amount,
        "plan_max_amount": amount,
        "plan_intervals": 1,
        "plan_interval_type": interval.upper(),
    })
    _known_plans.add(pid)
    return pid


def _add_months(when: datetime, months: int) -> datetime:
    month = when.month - 1 + months
    year, month = when.year + month // 12, month % 12 + 1
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))


def create_subscription(subscription_id: str, plan_id: str, amount: int, interval: str, email: str, phone: str,
                        workspace_id: str, return_url: str) -> str:
    """Returns the session id for Cashfree's hosted checkout. The authorisation charges the first period in full,
    so the first renewal is one period from now."""
    first_charge = _add_months(datetime.now(timezone.utc), 12 if interval == "year" else 1)
    data = _request("POST", "/subscriptions", {
        "subscription_id": subscription_id,
        "customer_details": {"customer_email": email, "customer_phone": phone},
        "plan_details": {"plan_id": plan_id},
        "authorization_details": {"authorization_amount": amount, "authorization_amount_refund": False},
        "subscription_first_charge_time": first_charge.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subscription_meta": {"return_url": return_url},
        "subscription_tags": {"workspace_id": workspace_id},
    })
    return data["subscription_session_id"]


def retrieve_subscription(subscription_id: str) -> dict:
    return _request("GET", f"/subscriptions/{subscription_id}")


def manage_subscription(subscription_id: str, action: str, plan_id: str | None = None) -> None:
    body: dict = {"subscription_id": subscription_id, "action": action}
    if plan_id:
        body["action_details"] = {"plan_id": plan_id}
    _request("POST", f"/subscriptions/{subscription_id}/manage", body)


def cancel_subscription(subscription_id: str) -> None:
    """Stops every future charge (account deletion, or the owner canceling)."""
    manage_subscription(subscription_id, "CANCEL")


def verify_event(payload: bytes, signature: str | None, timestamp: str | None) -> dict:
    """Raises ValueError unless Cashfree signed timestamp + body with our client secret."""
    if not settings.billing_enabled:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    if not signature or not timestamp:
        raise ValueError("missing signature")
    digest = hmac.new(settings.cashfree_client_secret.encode(), timestamp.encode() + payload, hashlib.sha256).digest()
    if not hmac.compare_digest(base64.b64encode(digest).decode(), signature):
        raise ValueError("bad signature")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bad payload") from exc
