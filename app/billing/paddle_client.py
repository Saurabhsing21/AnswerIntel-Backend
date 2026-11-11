"""The only module that talks to Paddle. Tests replace the network calls; signature checks stay real.

Checkout happens in the browser (Paddle.js); the server receives signed webhooks and, with PADDLE_API_KEY, opens the
customer portal, changes plans and cancels on account deletion.
"""

import hashlib
import hmac
import json
import logging
import time

import httpx

from app.common.config import settings
from app.common.errors import AppError

log = logging.getLogger(__name__)

# Paddle signs each delivery with the time it was sent; older ones are refused so a captured request can't be replayed later.
SIGNATURE_TOLERANCE_SECONDS = 300

_price_ids: dict[tuple[str, str], str] = {}


def _base() -> str:
    return "https://api.paddle.com" if settings.paddle_env == "production" else "https://sandbox-api.paddle.com"


def _request(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    if not settings.paddle_api_key:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    try:
        response = httpx.request(method, _base() + path, json=body, params=params, timeout=20,
                                 headers={"Authorization": f"Bearer {settings.paddle_api_key}"})
    except httpx.HTTPError as exc:
        raise AppError(502, "BILLING_PROVIDER_ERROR", "Could not reach the payment provider. Please try again.") from exc
    if response.status_code >= 400:
        error = (response.json() if response.headers.get("content-type", "").startswith("application/json") else {}).get("error") or {}
        log.warning("Paddle %s %s refused (%s): %s", method, path, response.status_code, error.get("detail") or response.text[:200])
        raise AppError(502, "BILLING_PROVIDER_ERROR", "The payment provider refused the request. Please try again.")
    return response.json()["data"]


def price_id_for(plan: str, interval: str) -> str:
    """The catalog price for a plan and period, found by the custom_data every price carries ({"plan", "interval"})."""
    if (plan, interval) not in _price_ids:
        for price in _request("GET", "/prices", params={"status": "active", "per_page": 200}):
            data = price.get("custom_data") or {}
            if data.get("plan") and data.get("interval"):
                _price_ids[(data["plan"], data["interval"])] = price["id"]
    if (plan, interval) not in _price_ids:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "This plan is not set up in the payment provider.")
    return _price_ids[(plan, interval)]


def change_price(subscription_id: str, price_id: str) -> dict:
    """Moves a subscription to another price now; Paddle charges or credits the difference for the rest of the period."""
    return _request("PATCH", f"/subscriptions/{subscription_id}", {
        "items": [{"price_id": price_id, "quantity": 1}],
        "proration_billing_mode": "prorated_immediately",
    })


def cancel_subscription(subscription_id: str) -> None:
    """Ends a subscription now (account deletion), so the customer is never billed again."""
    _request("POST", f"/subscriptions/{subscription_id}/cancel", {"effective_from": "immediately"})


def portal_url(customer_id: str, subscription_ids: list[str]) -> str:
    """A short-lived link that signs the customer in to Paddle's portal: invoices, payment method, cancel."""
    session = _request("POST", f"/customers/{customer_id}/portal-sessions", {"subscription_ids": subscription_ids})
    return session["urls"]["general"]["overview"]


def verify_event(payload: bytes, header: str | None, now: float | None = None) -> dict:
    """Raises ValueError unless Paddle signed this exact body with our notification secret (`ts=...;h1=...`)."""
    if not settings.paddle_webhook_secret:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    parts = [p.split("=", 1) for p in (header or "").split(";") if "=" in p]
    timestamp = next((v for k, v in parts if k == "ts"), None)
    signatures = [v for k, v in parts if k == "h1"]
    if not timestamp or not signatures:
        raise ValueError("missing signature")
    if not timestamp.isdigit() or abs((now or time.time()) - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
        raise ValueError("stale signature")
    expected = hmac.new(settings.paddle_webhook_secret.encode(), f"{timestamp}:".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise ValueError("bad signature")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bad payload") from exc
