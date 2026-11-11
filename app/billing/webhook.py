"""Paddle webhook. Mounted outside the per-user rate limit: Paddle has no user and retries from shared IPs.

The signature is checked first, on the raw body. The event id is then stored in the same transaction as its effect,
so a duplicate delivery is skipped and a failed one (rolled back, answered 500) is retried by Paddle. Deliveries can
arrive out of order: every write is an upsert, and an older copy of a subscription never overwrites a newer one.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.billing import paddle_client
from app.billing.emails import send_payment_failed
from app.billing.models import BillingEvent
from app.billing.service import apply_paddle_customer, apply_paddle_subscription, cancel_replaced, find_subscription
from app.common.database import SessionLocal
from app.common.errors import AppError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])

# Every subscription.* event carries the whole subscription, so they share one handler.
SUBSCRIPTION_EVENTS = (
    "subscription.created", "subscription.updated", "subscription.canceled", "subscription.activated",
    "subscription.past_due", "subscription.paused", "subscription.resumed", "subscription.trialing",
)
CUSTOMER_EVENTS = ("customer.created", "customer.updated")


def handle_event(event: dict) -> str:
    """Returns what happened, for logs and tests: duplicate, ignored or applied."""
    kind, data = event.get("event_type"), event.get("data") or {}
    with SessionLocal() as session:
        session.add(BillingEvent(id=event["event_id"], type=str(kind)[:100]))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return "duplicate"
        replaced = notify = None
        if kind in SUBSCRIPTION_EVENTS:
            existing = find_subscription(session, data)
            before = existing.status if existing else None
            sub, replaced = apply_paddle_subscription(session, data)
            result = "applied" if sub else "ignored"
            if sub and sub.status == "past_due" and before != "past_due":
                notify = (sub.workspace_id, sub.grace_ends_at)
        elif kind in CUSTOMER_EVENTS:
            apply_paddle_customer(session, data)
            result = "applied"
        elif kind == "transaction.completed":
            # The subscription events carry the plan; this one only confirms the payment, for the logs.
            log.info("Paddle transaction %s completed (subscription %s)", data.get("id"), data.get("subscription_id"))
            result = "applied"
        else:
            result = "ignored"
        session.commit()
    cancel_replaced(replaced)
    if notify:
        send_payment_failed(*notify)
    return result


@router.post("/webhook", include_in_schema=False)
async def paddle_webhook(request: Request):
    payload = await request.body()  # raw bytes: the signature covers the body exactly as sent
    try:
        event = paddle_client.verify_event(payload, request.headers.get("paddle-signature"))
    except ValueError:
        raise AppError(400, "INVALID_SIGNATURE", "Invalid Paddle signature.")
    result = await run_in_threadpool(handle_event, event)
    log.info("Paddle event %s (%s): %s", event.get("event_id"), event.get("event_type"), result)
    return {"received": True, "result": result}
