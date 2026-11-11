"""Billing: card-free trial, Cashfree checkout and webhooks, and per-plan limits that follow the subscription."""

import base64
import hashlib
import hmac
import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from app.billing import cashfree_client
from app.billing.emails import send_trial_notices
from app.billing.models import BillingEvent, Subscription
from app.billing.plans import PLANS, credits_for
from app.common.config import settings
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from app.prompts.models import Prompt
from app.providers.models import engines_for_project
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.scans.retention import purge_expired
from app.workspaces.models import Workspace
from tests.conftest import API, make_project, signup

SECRET = "cfsk_test_secret"
PHONE = "+14155550123"
PROJECT = {"brand_name": "Halden", "website": "https://halden.co", "description": "CRM", "category": "CRM software", "country": "US"}


class FakeCashfree:
    """Stands in for app.billing.cashfree_client's network calls; signature checks and plan ids stay real."""

    def __init__(self):
        self.subscriptions: dict[str, dict] = {}
        self.retrieved: list[str] = []
        self.checkouts: list[dict] = []
        self.managed: list[tuple] = []

    def ensure_plan(self, plan, interval, name, amount):
        return cashfree_client.plan_id(plan, interval, amount)

    def create_subscription(self, subscription_id, plan_id, amount, interval, email, phone, workspace_id, return_url):
        self.checkouts.append({"id": subscription_id, "plan_id": plan_id, "amount": amount, "email": email, "phone": phone,
                               "workspace_id": workspace_id, "return_url": return_url})
        return f"sub_session_{subscription_id}"

    def retrieve_subscription(self, subscription_id):
        self.retrieved.append(subscription_id)
        return json.loads(json.dumps(self.subscriptions[subscription_id]))

    def manage_subscription(self, subscription_id, action, plan_id=None):
        self.managed.append((subscription_id, action, plan_id))
        sub = self.subscriptions[subscription_id]
        if action == "CHANGE_PLAN":
            sub["plan_details"]["plan_id"] = plan_id
        elif action == "CANCEL":
            sub["subscription_status"], sub["next_schedule_date"] = "CANCELLED", None

    def cancel_subscription(self, subscription_id):
        self.manage_subscription(subscription_id, "CANCEL")


@pytest.fixture
def fake_cashfree(monkeypatch):
    fake = FakeCashfree()
    monkeypatch.setattr(settings, "cashfree_client_id", "TEST_x")
    monkeypatch.setattr(settings, "cashfree_client_secret", SECRET)
    for name in ("ensure_plan", "create_subscription", "retrieve_subscription", "manage_subscription", "cancel_subscription"):
        monkeypatch.setattr(cashfree_client, name, getattr(fake, name))
    return fake


@pytest.fixture
def outbox(monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("app.billing.emails.send_report_email", lambda to, subject, html: sent.append((to, subject)))
    return sent


def workspace_of(client, headers) -> str:
    return client.get(f"{API}/workspaces", headers=headers).json()[0]["id"]


def billing(client, headers, workspace_id):
    return client.get(f"{API}/workspaces/{workspace_id}/billing", headers=headers)


def cashfree_subscription(workspace_id, status="ACTIVE", plan="starter", interval="month") -> dict:
    amount = PLANS[plan].price_yearly if interval == "year" else PLANS[plan].price_monthly
    return {
        "subscription_id": f"ws_{uuid.uuid4().hex[:20]}",
        "cf_subscription_id": str(uuid.uuid4().int)[:16],
        "subscription_status": status,
        "plan_details": {"plan_id": cashfree_client.plan_id(plan, interval, amount)},
        "next_schedule_date": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "subscription_tags": {"workspace_id": workspace_id},
    }


def post_event(client, event_type, data, secret=SECRET, timestamp="1762850000000"):
    payload = json.dumps({"data": data, "event_time": datetime.now(timezone.utc).isoformat(), "type": event_type,
                          "nonce": uuid.uuid4().hex})
    signature = base64.b64encode(hmac.new(secret.encode(), (timestamp + payload).encode(), hashlib.sha256).digest()).decode()
    return client.post("/api/v1/billing/webhook", content=payload, headers={
        "x-webhook-signature": signature, "x-webhook-timestamp": timestamp, "content-type": "application/json"})


def payment(sub, payment_type="CHARGE", status="SUCCESS") -> dict:
    return {"subscription_id": sub["subscription_id"], "payment_type": payment_type, "payment_status": status}


def subscribe(client, fake, workspace_id, plan="starter", interval="month", status="ACTIVE") -> dict:
    """Simulate a completed checkout: Cashfree sends SUBSCRIPTION_AUTH_STATUS once the mandate is authorised."""
    sub = cashfree_subscription(workspace_id, status=status, plan=plan, interval=interval)
    fake.subscriptions[sub["subscription_id"]] = sub
    response = post_event(client, "SUBSCRIPTION_AUTH_STATUS", payment(sub, payment_type="AUTH"))
    assert response.status_code == 200 and response.json()["result"] == "applied"
    return sub


def set_subscription(workspace_id, **values):
    with SessionLocal() as session:
        session.execute(update(Subscription).where(Subscription.workspace_id == uuid.UUID(workspace_id)).values(**values))
        session.commit()


def add_member(client, owner, workspace_id):
    email = f"seat-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    return client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": email}, headers=owner)


def test_signup_has_no_plan_until_checkout_is_paid(client, unpaid_signups, fake_cashfree):
    headers = signup(client, "noplan")
    workspace_id = workspace_of(client, headers)
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "none" and body["state"] == "unsubscribed" and body["can_write"] is False
    assert body["trial_ends_at"] is None and body["can_manage"] is True
    assert body["usage"]["scans_30_days"] == 0
    blocked = client.post(f"{API}/projects", json=PROJECT, headers=headers)
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "SUBSCRIPTION_INACTIVE"
    assert blocked.json()["error"]["message"] == "Choose a plan to start scanning."

    checkout = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "starter", "phone": PHONE}, headers=headers)
    assert checkout.status_code == 200
    subscribe(client, fake_cashfree, workspace_id)
    assert billing(client, headers, workspace_id).json()["state"] == "active"
    assert client.post(f"{API}/projects", json=PROJECT, headers=headers).status_code == 200


def test_new_workspaces_start_without_a_plan_too(client, unpaid_signups):
    headers = signup(client, "noplanws")
    second = client.post(f"{API}/workspaces", json={"name": "Side project"}, headers=headers).json()["id"]
    assert billing(client, headers, second).json()["state"] == "unsubscribed"


def test_billing_endpoints_owner_only(client, fake_cashfree):
    owner = signup(client, "billowner")
    workspace_id = workspace_of(client, owner)
    member_email = f"billmember-{uuid.uuid4().hex}@example.com"
    client.post(f"{API}/auth/register", json={"email": member_email, "password": "password123"})
    login = client.post(f"{API}/auth/login", json={"email": member_email, "password": "password123"})
    member = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post(f"{API}/workspaces/{workspace_id}/members", json={"email": member_email, "role": "admin"}, headers=owner)
    stranger = signup(client, "billstranger")

    seen = billing(client, member, workspace_id)
    assert seen.status_code == 200 and seen.json()["can_manage"] is False
    for path in ("checkout", "change", "cancel", "sync"):
        denied = client.post(f"{API}/workspaces/{workspace_id}/billing/{path}", json={"plan": "pro", "phone": PHONE}, headers=member)
        assert denied.status_code == 403, path
    assert billing(client, stranger, workspace_id).status_code == 404
    assert client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "pro"}, headers=stranger).status_code == 404


def test_checkout_returns_a_cashfree_session_and_rejects_offsite_returns(client, fake_cashfree):
    headers = signup(client, "checkout")
    workspace_id = workspace_of(client, headers)
    url = f"{API}/workspaces/{workspace_id}/billing/checkout"

    no_phone = client.post(url, json={"plan": "pro"}, headers=headers)
    assert no_phone.status_code == 422 and no_phone.json()["error"]["code"] == "PHONE_REQUIRED"
    assert client.post(url, json={"plan": "pro", "phone": "call me"}, headers=headers).status_code == 422

    response = client.post(url, json={"plan": "pro", "interval": "year", "phone": PHONE, "return_path": "/projects/abc/billing"}, headers=headers)
    assert response.status_code == 200 and response.json() == {"session_id": f"sub_session_{fake_cashfree.checkouts[-1]['id']}", "mode": "sandbox"}
    sent = fake_cashfree.checkouts[-1]
    assert sent["plan_id"] == "seenlense_pro_year_usd960" and sent["amount"] == 960 and sent["workspace_id"] == workspace_id
    assert sent["phone"] == PHONE and sent["return_url"] == f"{settings.app_base_url}/billing/return?to=%2Fprojects%2Fabc%2Fbilling"
    body = billing(client, headers, workspace_id).json()
    assert body["has_billing_phone"] is True and body["has_billing_account"] is False  # nothing paid yet

    again = client.post(url, json={"plan": "starter"}, headers=headers)  # the phone is remembered
    assert again.status_code == 200 and fake_cashfree.checkouts[-1]["phone"] == PHONE
    assert fake_cashfree.checkouts[-1]["id"] != sent["id"]  # Cashfree needs a new id per attempt

    for bad in ("//evil.com", "https://evil.com", "evil.com"):
        assert client.post(url, json={"plan": "pro", "return_path": bad}, headers=headers).status_code == 422, bad
    assert client.post(url, json={"plan": "enterprise"}, headers=headers).status_code == 422


def test_checkout_without_cashfree_configured_says_so(client, monkeypatch):
    monkeypatch.setattr(settings, "cashfree_client_secret", "")
    headers = signup(client, "nocashfree")
    workspace_id = workspace_of(client, headers)
    response = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "pro", "phone": PHONE}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "BILLING_NOT_CONFIGURED"
    cancel = client.post(f"{API}/workspaces/{workspace_id}/billing/cancel", headers=headers)
    assert cancel.status_code == 409 and cancel.json()["error"]["code"] == "NO_ACTIVE_SUBSCRIPTION"


def test_webhook_upgrade_flips_the_plan_and_blocks_a_second_checkout(client, fake_cashfree):
    headers = signup(client, "upgrade")
    workspace_id = workspace_of(client, headers)
    sub = subscribe(client, fake_cashfree, workspace_id, plan="pro")

    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "pro" and body["state"] == "active" and body["interval"] == "month"
    assert body["current_period_end"] is not None and body["has_billing_account"] is True
    with SessionLocal() as session:
        row = session.scalar(select(Subscription).where(Subscription.workspace_id == uuid.UUID(workspace_id)))
        assert row.cashfree_subscription_id == sub["subscription_id"]

    again = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "starter", "phone": PHONE}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_SUBSCRIBED"


def test_failed_checkout_changes_nothing(client, fake_cashfree, outbox):
    headers = signup(client, "authfail")
    workspace_id = workspace_of(client, headers)
    before = billing(client, headers, workspace_id).json()
    sub = cashfree_subscription(workspace_id, status="INITIALIZED")
    fake_cashfree.subscriptions[sub["subscription_id"]] = sub
    post_event(client, "SUBSCRIPTION_PAYMENT_FAILED", payment(sub, payment_type="AUTH", status="FAILED"))
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == before["plan"] and body["has_billing_account"] is False and outbox == []


def test_sync_activates_a_paid_checkout_without_waiting_for_the_webhook(client, fake_cashfree):
    headers = signup(client, "sync")
    workspace_id = workspace_of(client, headers)
    url = f"{API}/workspaces/{workspace_id}/billing"
    assert client.post(f"{url}/sync", headers=headers).json() == {"synced": False}  # nothing started yet

    client.post(f"{url}/checkout", json={"plan": "growth", "phone": PHONE}, headers=headers)
    pending = fake_cashfree.checkouts[-1]["id"]
    sub = cashfree_subscription(workspace_id, status="INITIALIZED", plan="growth")
    sub["subscription_id"] = pending
    fake_cashfree.subscriptions[pending] = sub
    assert client.post(f"{url}/sync", headers=headers).json() == {"synced": False}  # not paid yet
    assert billing(client, headers, workspace_id).json()["has_billing_account"] is False

    sub["subscription_status"] = "ACTIVE"
    assert client.post(f"{url}/sync", headers=headers).json() == {"synced": True}
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "growth" and body["state"] == "active" and body["has_billing_account"] is True


def test_duplicate_event_is_ignored(client, fake_cashfree):
    headers = signup(client, "dupe")
    workspace_id = workspace_of(client, headers)
    sub = cashfree_subscription(workspace_id)
    fake_cashfree.subscriptions[sub["subscription_id"]] = sub
    payload = json.dumps({"data": payment(sub), "event_time": "2026-11-11T10:00:00+05:30", "type": "SUBSCRIPTION_PAYMENT_SUCCESS"})
    signature = base64.b64encode(hmac.new(SECRET.encode(), ("1" + payload).encode(), hashlib.sha256).digest()).decode()
    send = lambda: client.post("/api/v1/billing/webhook", content=payload, headers={"x-webhook-signature": signature, "x-webhook-timestamp": "1"})
    assert send().json()["result"] == "applied" and send().json()["result"] == "duplicate"
    assert fake_cashfree.retrieved.count(sub["subscription_id"]) == 1
    with SessionLocal() as session:
        assert session.get(BillingEvent, "cf_" + hashlib.sha256(payload.encode()).hexdigest()).type == "SUBSCRIPTION_PAYMENT_SUCCESS"


def test_bad_or_missing_signature_is_rejected(client, fake_cashfree):
    assert post_event(client, "SUBSCRIPTION_STATUS_CHANGED", {"subscription_id": "x"}, secret="wrong").status_code == 400
    unsigned = client.post("/api/v1/billing/webhook", content=json.dumps({"type": "x", "data": {}}))
    assert unsigned.status_code == 400 and unsigned.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert fake_cashfree.retrieved == []


def test_unrelated_event_is_recorded_and_ignored(client, fake_cashfree):
    assert post_event(client, "SUBSCRIPTION_REFUND_STATUS", {"subscription_id": "x"}).json()["result"] == "ignored"


def test_payment_failed_gives_a_grace_period_then_lapses(client, fake_cashfree, outbox):
    headers = signup(client, "pastdue")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    sub = subscribe(client, fake_cashfree, workspace_id)

    # UPI AutoPay keeps the subscription ACTIVE while Cashfree retries; the failed charge alone makes it past due.
    assert post_event(client, "SUBSCRIPTION_PAYMENT_FAILED", payment(sub, status="FAILED")).json()["result"] == "applied"
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "past_due" and body["can_write"] is True
    grace = datetime.fromisoformat(body["grace_ends_at"]) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < grace <= timedelta(days=7)
    assert outbox and outbox[-1][1] == "Your payment failed"

    fake_cashfree.subscriptions[sub["subscription_id"]]["subscription_status"] = "ON_HOLD"  # cards: retries are over
    post_event(client, "SUBSCRIPTION_STATUS_CHANGED", {"subscription_details": {"subscription_id": sub["subscription_id"]}})
    assert billing(client, headers, workspace_id).json()["grace_ends_at"] == body["grace_ends_at"]  # the clock is not reset

    set_subscription(workspace_id, grace_ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "lapsed" and body["can_write"] is False
    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "SUBSCRIPTION_INACTIVE" and blocked.json()["error"]["limit"] == "subscription"
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).status_code == 200  # still readable

    fake_cashfree.subscriptions[sub["subscription_id"]]["subscription_status"] = "ACTIVE"  # the retry paid
    assert post_event(client, "SUBSCRIPTION_PAYMENT_SUCCESS", payment(sub)).json()["result"] == "applied"
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "active" and body["grace_ends_at"] is None


def test_cancel_keeps_the_paid_period_then_lapses(client, fake_cashfree):
    headers = signup(client, "cancel")
    workspace_id = workspace_of(client, headers)
    old = subscribe(client, fake_cashfree, workspace_id)

    canceled = client.post(f"{API}/workspaces/{workspace_id}/billing/cancel", headers=headers)
    assert canceled.status_code == 200 and fake_cashfree.managed[-1] == (old["subscription_id"], "CANCEL", None)
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "active" and body["cancel_at_period_end"] is True and body["current_period_end"] is not None
    assert client.post(f"{API}/workspaces/{workspace_id}/billing/cancel", headers=headers).status_code == 409

    set_subscription(workspace_id, current_period_end=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert billing(client, headers, workspace_id).json()["state"] == "lapsed"

    new = subscribe(client, fake_cashfree, workspace_id, plan="pro", interval="year")
    post_event(client, "SUBSCRIPTION_STATUS_CHANGED", {"subscription_id": old["subscription_id"]})  # late event for the old one
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "pro" and body["state"] == "active" and body["cancel_at_period_end"] is False
    with SessionLocal() as session:
        current = session.scalar(select(Subscription.cashfree_subscription_id).where(Subscription.workspace_id == uuid.UUID(workspace_id)))
    assert current == new["subscription_id"]


def test_downgrade_changes_the_plan_in_place(client, fake_cashfree):
    headers = signup(client, "downgrade")
    workspace_id = workspace_of(client, headers)
    url = f"{API}/workspaces/{workspace_id}/billing/change"
    assert client.post(url, json={"plan": "pro"}, headers=headers).status_code == 409  # nothing to change yet
    sub = subscribe(client, fake_cashfree, workspace_id, plan="pro", interval="year")

    same = client.post(url, json={"plan": "pro", "interval": "year"}, headers=headers)
    assert same.status_code == 409 and same.json()["error"]["code"] == "SAME_PLAN"
    changed = client.post(url, json={"plan": "growth", "interval": "month"}, headers=headers)
    assert changed.status_code == 200 and changed.json() == {"plan": "growth", "interval": "month"}
    assert fake_cashfree.managed[-1] == (sub["subscription_id"], "CHANGE_PLAN", "seenlense_growth_month_usd50")
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "growth" and body["interval"] == "month" and body["limits"]["schedules"] is True


def test_upgrade_is_a_new_checkout_and_cancels_the_old_subscription_once_paid(client, fake_cashfree):
    headers = signup(client, "upgradeplan")
    workspace_id = workspace_of(client, headers)
    client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "starter", "phone": PHONE}, headers=headers)
    old = subscribe(client, fake_cashfree, workspace_id)

    # Cashfree never raises a mandate above what was approved, so a dearer plan goes through checkout.
    response = client.post(f"{API}/workspaces/{workspace_id}/billing/change", json={"plan": "pro", "interval": "year"}, headers=headers)
    assert response.status_code == 200 and response.json()["session_id"].startswith("sub_session_")
    assert fake_cashfree.managed == [] and fake_cashfree.checkouts[-1]["plan_id"] == "seenlense_pro_year_usd960"
    assert billing(client, headers, workspace_id).json()["plan"] == "starter"  # nothing changes until it is paid

    new = cashfree_subscription(workspace_id, plan="pro", interval="year")
    new["subscription_id"] = fake_cashfree.checkouts[-1]["id"]
    fake_cashfree.subscriptions[new["subscription_id"]] = new
    assert client.post(f"{API}/workspaces/{workspace_id}/billing/sync", headers=headers).json() == {"synced": True}
    assert fake_cashfree.managed == [(old["subscription_id"], "CANCEL", None)]
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "pro" and body["interval"] == "year" and body["state"] == "active"

    post_event(client, "SUBSCRIPTION_STATUS_CHANGED", {"subscription_id": old["subscription_id"]})  # the old one's cancel
    assert billing(client, headers, workspace_id).json()["plan"] == "pro"


def test_expired_legacy_trial_is_read_only(client):
    headers = signup(client, "expired")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    # Only workspaces that predate billing have a trial; it cannot be started any more.
    set_subscription(workspace_id, plan="trial", status="trialing", interval=None,
                     trial_ends_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    prompt = {"text": "best crm", "category": "CATEGORY", "intent": "DISCOVERY"}
    attempts = {
        "scan": client.post(f"{API}/projects/{project_id}/scans", headers=headers),
        "prompt": client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers),
        "generate": client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers),
        "competitor": client.post(f"{API}/projects/{project_id}/competitors", json={"name": "Orbit", "website": "https://orbit.io"}, headers=headers),
        "project": client.post(f"{API}/projects", json=PROJECT, headers=headers),
        "invite": add_member(client, headers, workspace_id),
    }
    for name, response in attempts.items():
        assert response.status_code == 402, (name, response.json())
        assert response.json()["error"]["code"] == "SUBSCRIPTION_INACTIVE", name
    for path in ("", "/dashboard", "/competitors", "/prompts", "/scans"):
        assert client.get(f"{API}/projects/{project_id}{path}", headers=headers).status_code == 200, path


def test_starter_limits_are_enforced(client, fake_cashfree):
    headers = signup(client, "starter")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)  # two competitors
    subscribe(client, fake_cashfree, workspace_id)
    assert billing(client, headers, workspace_id).json()["plan"] == "starter"
    pid = uuid.UUID(project_id)

    def error(response):
        return response.status_code, response.json()["error"]["code"], response.json()["error"].get("limit")

    assert client.post(f"{API}/projects", json=PROJECT, headers=headers).status_code == 200  # 2 projects
    assert error(client.post(f"{API}/projects", json=PROJECT, headers=headers)) == (402, "PLAN_LIMIT", "projects")

    with SessionLocal() as session:  # 18 more competitors fill Starter's 20
        session.add_all([Competitor(project_id=pid, name=f"Rival {i}", website=f"https://rival{i}.io") for i in range(18)])
        session.commit()
    extra = client.post(f"{API}/projects/{project_id}/competitors", json={"name": "Nimbus", "website": "https://nimbus.io"}, headers=headers)
    assert error(extra) == (409, "COMPETITOR_LIMIT", "competitors")

    # Weekly scans are on every plan; experiments start at Growth.
    assert client.put(f"{API}/projects/{project_id}/schedule", json={"enabled": True}, headers=headers).status_code == 200
    experiment = client.post(f"{API}/projects/{project_id}/experiments", json={"name": "FAQ page"}, headers=headers)
    assert error(experiment) == (402, "PLAN_LIMIT", "experiments")

    for _ in range(5):  # seats are unlimited on every plan
        assert add_member(client, headers, workspace_id).status_code == 200

    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    assert client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers).status_code == 200
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert scan["total_runs"] == len(engines_for_project(None))  # every engine on every plan

    with SessionLocal() as session:  # one more scan today fills Starter's two; 49 more prompts fill 50
        session.add(Scan(project_id=pid, status="completed"))
        session.add_all([Prompt(project_id=pid, text=f"prompt {i}", category="CATEGORY", intent="DISCOVERY", source="user") for i in range(49)])
        session.commit()
    assert error(client.post(f"{API}/projects/{project_id}/scans", headers=headers)) == (429, "SCAN_LIMIT_REACHED", "scans_per_day")
    extra = client.post(f"{API}/projects/{project_id}/prompts", json={**prompt, "text": "one too many"}, headers=headers)
    assert error(extra) == (409, "PROMPT_LIMIT", "active_prompts")

    usage = billing(client, headers, workspace_id).json()["usage"]
    assert usage["projects"] == 2 and usage["seats"] == 6 and usage["scans_today"] == 2 and usage["active_prompts"] == 50
    first = next(p for p in usage["per_project"] if p["id"] == project_id)
    assert first["competitors"] == 20 and first["active_prompts"] == 50


def test_credit_weights_per_engine():
    keys = ("chatgpt_search", "gemini", "perplexity", "claude", "deepseek", "llama", "mistral")
    assert {k: credits_for(k) for k in keys} == {
        "chatgpt_search": 1, "gemini": 1.25, "perplexity": 0.5, "claude": 0.5, "deepseek": 0.25, "llama": 0.25, "mistral": 0.25,
    }
    assert credits_for("grok") == credits_for("chatgpt") == 1  # an engine with no weight costs one credit


def test_plans_set_prompts_credits_and_engines():
    table = {key: (PLANS[key].active_prompts, PLANS[key].credits_per_month) for key in ("free", "starter", "growth", "pro", "trial")}
    assert table == {"free": (10, 10), "starter": (50, 650), "growth": (120, 1650), "pro": (200, 3300), "trial": (120, 1650)}
    assert PLANS["free"].allowed_engines == ("chatgpt_search",)
    assert PLANS["starter"].allowed_engines == ("chatgpt_search", "perplexity")
    assert PLANS["growth"].allowed_engines == PLANS["trial"].allowed_engines == ("chatgpt_search", "perplexity", "claude")
    assert set(PLANS["pro"].allowed_engines) == {"chatgpt_search", "perplexity", "claude", "gemini", "deepseek", "llama", "mistral"}


def test_a_scan_is_charged_credits_by_engine(client, fake_cashfree):
    headers = signup(client, "credits")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id, plan="pro")
    engines = ["chatgpt_search", "perplexity", "claude", "gemini"]
    assert client.put(f"{API}/projects/{project_id}", json={"engines": engines}, headers=headers).status_code == 200
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers)

    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    assert scan["total_runs"] == 4 and scan["credits"] == 3.25  # 1 + 0.5 + 0.5 + 1.25
    with SessionLocal() as session:
        assert session.get(Scan, scan["id"]).credits == Decimal("3.25")
    body = billing(client, headers, workspace_id).json()
    assert body["usage"]["credits_30_days"] == 3.25 and "answers_30_days" not in body["usage"]
    assert body["limits"]["credits_per_month"] == 3300 and "answers_per_month" not in body["limits"]


def test_monthly_credit_cap_refuses_a_scan_that_would_go_over(client, fake_cashfree):
    headers = signup(client, "credits-cap")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id)  # Starter: 650 credits in any 30 days
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers)
    needed = 1.5  # one prompt on ChatGPT Search (1) and Perplexity (0.5)
    with SessionLocal() as session:  # older scans (not today, so the daily guard stays out of it)
        old = Scan(project_id=uuid.UUID(project_id), status="completed", total_runs=500, credits=Decimal("648.75"),
                   created_at=datetime.now(timezone.utc) - timedelta(days=3))
        session.add(old)
        session.commit()
        old_id = old.id

    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    error = blocked.json()["error"]
    assert blocked.status_code == 402 and error["code"] == "PLAN_LIMIT" and error["limit"] == "credits_per_month"
    assert error["message"].startswith("This scan needs 1.5 credits and 1.25 are left of your 650")
    assert billing(client, headers, workspace_id).json()["usage"]["credits_30_days"] == 648.75

    with SessionLocal() as session:  # exactly what is left still fits
        session.execute(update(Scan).where(Scan.id == old_id).values(credits=650 - needed))
        session.commit()
    allowed = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert allowed.status_code == 200 and allowed.json()["credits"] == needed and allowed.json()["total_runs"] == 2


def test_credits_roll_off_after_30_days(client, fake_cashfree):
    headers = signup(client, "credits-roll")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id)
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers)
    with SessionLocal() as session:  # a full month's credits, a month ago
        session.add(Scan(project_id=uuid.UUID(project_id), status="completed", credits=650,
                         created_at=datetime.now(timezone.utc) - timedelta(days=31)))
        session.commit()
    assert billing(client, headers, workspace_id).json()["usage"]["credits_30_days"] == 0
    assert client.post(f"{API}/projects/{project_id}/scans", headers=headers).status_code == 200


def test_prompt_pool_is_shared_by_every_project(client, fake_cashfree):
    headers = signup(client, "pool")
    workspace_id = workspace_of(client, headers)
    first = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id)  # Starter: 50 prompts in total
    second = client.post(f"{API}/projects", json=PROJECT, headers=headers).json()["id"]
    with SessionLocal() as session:
        session.add_all([Prompt(project_id=uuid.UUID(first), text=f"prompt {i}", category="CATEGORY",
                                intent="DISCOVERY", source="user") for i in range(50)])
        session.commit()
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    refused = client.post(f"{API}/projects/{second}/prompts", json=prompt, headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["limit"] == "active_prompts"
    error = refused.json()["error"]  # says which project holds the pool, so the user knows where to turn questions off
    assert error["details"] == {"holders": [{"project_id": first, "brand": "Halden", "active": 50}], "limit": 50}
    assert error["message"] == "Halden is using all 50 of your plan's questions. Turn some off there, or upgrade."
    generated = client.post(f"{API}/projects/{second}/prompts/generate", headers=headers).json()
    assert generated["created"] > 0 and not any(p["is_active"] for p in generated["prompts"])  # kept for review
    assert generated["pool_full"]["holders"] == error["details"]["holders"] and generated["pool_full"]["limit"] == 50
    assert "Halden is using all 50" in generated["pool_full"]["message"]

    toggled = client.patch(f"{API}/projects/{second}/prompts/{generated['prompts'][0]['id']}", json={"is_active": True}, headers=headers)
    assert toggled.status_code == 409 and toggled.json()["error"]["details"]["holders"][0]["project_id"] == first


def test_pool_error_lists_every_project_holding_it(client, fake_cashfree):
    headers = signup(client, "poolmany")
    workspace_id = workspace_of(client, headers)
    first = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id)
    second = client.post(f"{API}/projects", json={**PROJECT, "brand_name": "Bachatt"}, headers=headers).json()["id"]
    with SessionLocal() as session:
        for project, count in ((first, 30), (second, 20)):
            session.add_all([Prompt(project_id=uuid.UUID(project), text=f"{project} {i}", category="CATEGORY",
                                    intent="DISCOVERY", source="user") for i in range(count)])
        session.commit()
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    refused = client.post(f"{API}/projects/{second}/prompts", json=prompt, headers=headers).json()["error"]
    assert [(h["brand"], h["active"]) for h in refused["details"]["holders"]] == [("Halden", 30), ("Bachatt", 20)]
    assert refused["message"] == "Your projects are using all 50 of your plan's questions: Halden (30), Bachatt (20). Turn some off, or upgrade."
    accepted = client.post(f"{API}/projects/{second}/prompts/accept", json={"prompts": [{**prompt, "importance": 0.5}]}, headers=headers).json()
    assert accepted["inactive"] == 1 and len(accepted["pool_full"]["holders"]) == 2


def test_growth_checkout_and_limits(client, fake_cashfree):
    headers = signup(client, "growth")
    workspace_id = workspace_of(client, headers)
    response = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "growth", "interval": "year", "phone": PHONE}, headers=headers)
    assert response.status_code == 200 and fake_cashfree.checkouts[-1]["plan_id"] == "seenlense_growth_year_usd480"
    subscribe(client, fake_cashfree, workspace_id, plan="growth")
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "growth" and body["limits"]["projects"] == 4 and body["limits"]["schedules"] is True


def test_pro_allows_what_starter_does_not(client, fake_cashfree):
    headers = signup(client, "pro")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_cashfree, workspace_id, plan="pro")
    assert client.post(f"{API}/projects", json=PROJECT, headers=headers).status_code == 200
    assert client.put(f"{API}/projects/{project_id}/schedule", json={"enabled": True}, headers=headers).status_code == 200


def test_trial_notices_are_sent_once(client, outbox):
    headers = signup(client, "notice")
    workspace_id = workspace_of(client, headers)
    email = client.get(f"{API}/auth/me", headers=headers).json()["email"]
    now = datetime.now(timezone.utc)
    set_subscription(workspace_id, plan="trial", status="trialing", trial_ends_at=now + timedelta(days=2))

    send_trial_notices(now)
    send_trial_notices(now)
    assert outbox.count((email, "Your trial ends in 3 days")) == 1

    send_trial_notices(now + timedelta(days=3))
    send_trial_notices(now + timedelta(days=4))
    assert outbox.count((email, "Your trial has ended")) == 1


def test_retention_follows_each_workspaces_plan(client, fake_cashfree):
    def scanned(prefix):
        headers = signup(client, prefix)
        project_id = make_project(client, headers)
        client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
        scan_id = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()["id"]
        return workspace_of(client, headers), scan_id

    starter_ws, starter_scan = scanned("retstarter")
    subscribe(client, fake_cashfree, starter_ws)
    _, pro_scan = scanned("retpro")
    seven_months_ago = datetime.now(timezone.utc) - timedelta(days=210)
    with SessionLocal() as session:
        session.execute(
            update(AIResponseRecord).where(AIResponseRecord.scan_id.in_([starter_scan, pro_scan])).values(created_at=seven_months_ago)
        )
        session.commit()

    purge_expired(datetime.now(timezone.utc), raw_response_days=365)
    with SessionLocal() as session:
        def remaining(scan_id):
            return session.query(AIResponseRecord).filter(AIResponseRecord.scan_id == scan_id).count()
        assert remaining(starter_scan) == 0  # Starter keeps 6 months
        assert remaining(pro_scan) > 0  # Pro keeps 12


def test_backfill_gives_pre_billing_workspaces_a_trial(client):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/fc715186ae31_add_billing_subscriptions_and_stripe_.py"
    spec = importlib.util.spec_from_file_location("billing_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with SessionLocal() as session:
        workspace = Workspace(name="Made before billing")
        session.add(workspace)
        session.commit()
        session.execute(text(migration.BACKFILL_TRIALS))
        session.execute(text(migration.BACKFILL_TRIALS))  # safe to run twice
        session.commit()
        rows = session.scalars(select(Subscription).where(Subscription.workspace_id == workspace.id)).all()
        assert len(rows) == 1 and rows[0].plan == "trial" and rows[0].status == "trialing"
        assert rows[0].trial_ends_at > datetime.now(timezone.utc) + timedelta(days=13)
        session.delete(workspace)
        session.commit()


def test_credits_migration_backfills_one_credit_per_answer(client):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/b8d4f2a6c913_add_scans_credits.py"
    spec = importlib.util.spec_from_file_location("credits_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    headers = signup(client, "credits-backfill")
    project_id = uuid.UUID(make_project(client, headers))
    with SessionLocal() as session:
        scan = Scan(project_id=project_id, status="completed", total_runs=7)
        session.add(scan)
        session.commit()
        assert scan.credits == 0
        session.execute(text(migration.BACKFILL_CREDITS))
        session.commit()
        session.refresh(scan)
        assert scan.credits == 7  # before credits, every answer counted as one
