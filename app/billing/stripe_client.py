"""The only module that talks to Stripe. Tests replace these functions; nothing else imports stripe."""

import json

import stripe

from app.common.config import settings
from app.common.errors import AppError


def _client() -> stripe.StripeClient:
    if not settings.billing_enabled:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    return stripe.StripeClient(settings.stripe_secret_key)


def _call(fn):
    try:
        return fn()
    except stripe.StripeError as exc:
        raise AppError(502, "BILLING_PROVIDER_ERROR", "Could not reach the payment provider. Please try again.") from exc


def create_customer(email: str, workspace_id: str) -> str:
    client = _client()
    return _call(lambda: client.v1.customers.create(params={"email": email, "metadata": {"workspace_id": workspace_id}})).id


def create_checkout_session(customer_id: str, price_id: str, workspace_id: str, success_url: str, cancel_url: str) -> str:
    client = _client()
    session = _call(lambda: client.v1.checkout.sessions.create(params={
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": workspace_id,
        "metadata": {"workspace_id": workspace_id},
        "subscription_data": {"metadata": {"workspace_id": workspace_id}},
        "success_url": success_url,
        "cancel_url": cancel_url,
    }))
    return session.url


def create_portal_session(customer_id: str, return_url: str) -> str:
    client = _client()
    return _call(lambda: client.v1.billing_portal.sessions.create(params={"customer": customer_id, "return_url": return_url})).url


def retrieve_subscription(subscription_id: str) -> dict:
    client = _client()
    return _call(lambda: client.v1.subscriptions.retrieve(subscription_id)).to_dict()


def verify_event(payload: bytes, signature: str | None) -> dict:
    """Raises ValueError unless the payload was signed with our webhook secret in the last 5 minutes."""
    if not settings.stripe_webhook_secret:
        raise AppError(503, "BILLING_NOT_CONFIGURED", "Billing is not configured on this server.")
    if not signature:
        raise ValueError("missing signature")
    try:
        stripe.WebhookSignature.verify_header(payload.decode("utf-8"), signature, settings.stripe_webhook_secret, tolerance=300)
    except (stripe.SignatureVerificationError, UnicodeDecodeError) as exc:
        raise ValueError("bad signature") from exc
    return json.loads(payload)
