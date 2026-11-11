"""Cashfree subscription webhook. Mounted outside the per-user rate limit: Cashfree has no user and retries from
shared IPs.

The signature is checked first, then the event is stored in the same transaction as its effect, so a duplicate
delivery is skipped and a failed one (rolled back, answered 500) is retried by Cashfree.
"""

import hashlib
import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.billing import cashfree_client
from app.billing.emails import send_payment_failed
from app.billing.models import BillingEvent
from app.billing.service import apply_and_replace, cancel_replaced
from app.common.database import SessionLocal
from app.common.errors import AppError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])

SUBSCRIPTION_EVENTS = (
    "SUBSCRIPTION_STATUS_CHANGED", "SUBSCRIPTION_AUTH_STATUS", "SUBSCRIPTION_PAYMENT_SUCCESS", "SUBSCRIPTION_PAYMENT_FAILED",
)


def _subscription_id(event: dict) -> str | None:
    if event.get("type") not in SUBSCRIPTION_EVENTS:
        return None
    data = event.get("data") or {}
    return data.get("subscription_id") or (data.get("subscription_details") or {}).get("subscription_id")


def _renewal_failed(event: dict) -> bool:
    """A failed renewal charge. A failed AUTH is a checkout that never paid, which changes nothing."""
    data = event.get("data") or {}
    return event.get("type") == "SUBSCRIPTION_PAYMENT_FAILED" and data.get("payment_type") != "AUTH"


def handle_event(event: dict, event_id: str) -> str:
    """Returns what happened, for logs and tests: duplicate, ignored or applied."""
    subscription_id = _subscription_id(event)
    with SessionLocal() as session:
        session.add(BillingEvent(id=event_id, type=str(event.get("type"))[:100]))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return "duplicate"
        if not subscription_id:
            session.commit()
            return "ignored"
        # Never trust the event's copy: fetch the subscription as it is now, so out-of-order events cannot regress it.
        data = cashfree_client.retrieve_subscription(subscription_id)
        failed = _renewal_failed(event)
        sub, replaced = apply_and_replace(session, data, charge_failed=failed)
        session.commit()
        notify = (sub.workspace_id, sub.grace_ends_at) if sub and failed and sub.status == "past_due" else None
    cancel_replaced(replaced)
    if notify:
        send_payment_failed(*notify)
    return "applied" if sub else "ignored"


@router.post("/webhook", include_in_schema=False)
async def cashfree_webhook(request: Request):
    payload = await request.body()
    try:
        event = cashfree_client.verify_event(
            payload, request.headers.get("x-webhook-signature"), request.headers.get("x-webhook-timestamp")
        )
    except ValueError:
        raise AppError(400, "INVALID_SIGNATURE", "Invalid Cashfree signature.")
    # Cashfree sends no event id; a redelivery carries the same body.
    event_id = "cf_" + hashlib.sha256(payload).hexdigest()
    result = await run_in_threadpool(handle_event, event, event_id)
    log.info("Cashfree event %s (%s): %s", event_id, event.get("type"), result)
    return {"received": True, "result": result}
