"""Stripe webhook. Mounted outside the per-user rate limit: Stripe has no user and retries from shared IPs.

The signature is checked first, then the event id is stored in the same transaction as its effect, so a
duplicate delivery is skipped and a failed one (rolled back, answered 500) is retried by Stripe.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.billing import stripe_client
from app.billing.emails import send_payment_failed
from app.billing.models import StripeEvent
from app.billing.service import apply_stripe_subscription
from app.common.database import SessionLocal
from app.common.errors import AppError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])

SUBSCRIPTION_EVENTS = ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted")


def _invoice_subscription(invoice: dict) -> str | None:
    # Older API versions put it on the invoice; newer ones under parent.subscription_details.
    details = ((invoice.get("parent") or {}).get("subscription_details") or {})
    return invoice.get("subscription") or details.get("subscription")


def _subscription_id(event: dict) -> str | None:
    obj = event["data"]["object"]
    if event["type"] == "checkout.session.completed":
        return obj.get("subscription")
    if event["type"] in SUBSCRIPTION_EVENTS:
        return obj.get("id")
    if event["type"] in ("invoice.paid", "invoice.payment_failed"):
        return _invoice_subscription(obj)
    return None


def handle_event(event: dict) -> str:
    """Returns what happened, for logs and tests: duplicate, ignored or applied."""
    subscription_id = _subscription_id(event)
    with SessionLocal() as session:
        session.add(StripeEvent(id=event["id"], type=event["type"]))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return "duplicate"
        if not subscription_id:
            session.commit()
            return "ignored"
        # Never trust the event's copy: fetch the subscription as it is now, so out-of-order events cannot regress it.
        data = stripe_client.retrieve_subscription(subscription_id)
        if event["type"] == "checkout.session.completed":
            reference = event["data"]["object"].get("client_reference_id")
            data["metadata"] = {"workspace_id": reference, **(data.get("metadata") or {})}
        sub = apply_stripe_subscription(session, data)
        session.commit()
        failed = (sub.workspace_id, sub.grace_ends_at) if sub and event["type"] == "invoice.payment_failed" else None
    if failed:
        send_payment_failed(*failed)
    return "applied" if sub else "ignored"


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    payload = await request.body()
    try:
        event = stripe_client.verify_event(payload, request.headers.get("stripe-signature"))
    except ValueError:
        raise AppError(400, "INVALID_SIGNATURE", "Invalid Stripe signature.")
    result = await run_in_threadpool(handle_event, event)
    log.info("Stripe event %s (%s): %s", event.get("id"), event.get("type"), result)
    return {"received": True, "result": result}
