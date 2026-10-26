"""Billing: card-free trial, Stripe Checkout and webhooks, and per-plan limits that follow the subscription."""

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import stripe
from sqlalchemy import select, text, update

from app.billing import stripe_client
from app.billing.emails import send_trial_notices
from app.billing.models import StripeEvent, Subscription
from app.common.config import settings
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from app.prompts.models import Prompt
from app.providers.models import V1_MODELS
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.scans.retention import purge_expired
from app.workspaces.models import Workspace
from tests.conftest import API, make_project, signup

SECRET = "whsec_test_secret"
PRICES = {
    "stripe_price_starter_monthly": "price_starter_m",
    "stripe_price_starter_yearly": "price_starter_y",
    "stripe_price_growth_monthly": "price_growth_m",
    "stripe_price_growth_yearly": "price_growth_y",
    "stripe_price_pro_monthly": "price_pro_m",
    "stripe_price_pro_yearly": "price_pro_y",
}
PROJECT = {"brand_name": "Halden", "website": "https://halden.co", "description": "CRM", "category": "CRM software", "country": "US"}


class FakeStripe:
    """Stands in for app.billing.stripe_client's network calls; signature checks stay real."""

    def __init__(self):
        self.subscriptions: dict[str, dict] = {}
        self.retrieved: list[str] = []
        self.checkouts: list[dict] = []

    def create_customer(self, email, workspace_id):
        return f"cus_{uuid.uuid4().hex[:12]}"

    def create_checkout_session(self, customer_id, price_id, workspace_id, success_url, cancel_url):
        self.checkouts.append({"customer": customer_id, "price": price_id, "workspace_id": workspace_id,
                               "success_url": success_url, "cancel_url": cancel_url})
        return "https://checkout.stripe.test/session"

    def create_portal_session(self, customer_id, return_url):
        return f"https://billing.stripe.test/{customer_id}"

    def retrieve_subscription(self, subscription_id):
        self.retrieved.append(subscription_id)
        return json.loads(json.dumps(self.subscriptions[subscription_id]))


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", SECRET)
    for key, value in PRICES.items():
        monkeypatch.setattr(settings, key, value)
    for name in ("create_customer", "create_checkout_session", "create_portal_session", "retrieve_subscription"):
        monkeypatch.setattr(stripe_client, name, getattr(fake, name))
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


def stripe_subscription(workspace_id, status="active", price="price_starter_m", metadata=True) -> dict:
    return {
        "id": f"sub_{uuid.uuid4().hex[:12]}",
        "object": "subscription",
        "customer": f"cus_{uuid.uuid4().hex[:12]}",
        "status": status,
        "cancel_at_period_end": False,
        "metadata": {"workspace_id": workspace_id} if metadata else {},
        "items": {"data": [{"price": {"id": price}, "current_period_end": int(datetime.now(timezone.utc).timestamp()) + 30 * 86400}]},
    }


def post_event(client, event_type, obj, event_id=None, secret=SECRET):
    payload = json.dumps({"id": event_id or f"evt_{uuid.uuid4().hex}", "type": event_type, "data": {"object": obj}})
    header = stripe.WebhookSignature.generate_signature_header(payload, secret)
    return client.post("/api/v1/billing/webhook", content=payload, headers={"stripe-signature": header, "content-type": "application/json"})


def subscribe(client, fake, workspace_id, plan_price="price_starter_m", status="active") -> dict:
    """Simulate a completed Checkout: Stripe sends checkout.session.completed for a new subscription."""
    sub = stripe_subscription(workspace_id, status=status, price=plan_price, metadata=False)
    fake.subscriptions[sub["id"]] = sub
    event = {"object": "checkout.session", "client_reference_id": workspace_id, "customer": sub["customer"], "subscription": sub["id"]}
    response = post_event(client, "checkout.session.completed", event)
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


def test_signup_has_no_plan_until_checkout_is_paid(client, unpaid_signups, fake_stripe):
    headers = signup(client, "noplan")
    workspace_id = workspace_of(client, headers)
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "none" and body["state"] == "unsubscribed" and body["can_write"] is False
    assert body["trial_ends_at"] is None and body["can_manage"] is True
    assert body["usage"]["scans_30_days"] == 0
    blocked = client.post(f"{API}/projects", json=PROJECT, headers=headers)
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "SUBSCRIPTION_INACTIVE"
    assert blocked.json()["error"]["message"] == "Choose a plan to start scanning."

    checkout = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "starter"}, headers=headers)
    assert checkout.status_code == 200
    subscribe(client, fake_stripe, workspace_id)
    assert billing(client, headers, workspace_id).json()["state"] == "active"
    assert client.post(f"{API}/projects", json=PROJECT, headers=headers).status_code == 200


def test_new_workspaces_start_without_a_plan_too(client, unpaid_signups):
    headers = signup(client, "noplanws")
    second = client.post(f"{API}/workspaces", json={"name": "Side project"}, headers=headers).json()["id"]
    assert billing(client, headers, second).json()["state"] == "unsubscribed"


def test_billing_endpoints_owner_only(client, fake_stripe):
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
    for path in ("checkout", "portal"):
        denied = client.post(f"{API}/workspaces/{workspace_id}/billing/{path}", json={"plan": "pro"}, headers=member)
        assert denied.status_code == 403, path
    assert billing(client, stranger, workspace_id).status_code == 404
    assert client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "pro"}, headers=stranger).status_code == 404


def test_checkout_returns_a_stripe_url_and_rejects_offsite_returns(client, fake_stripe):
    headers = signup(client, "checkout")
    workspace_id = workspace_of(client, headers)
    url = f"{API}/workspaces/{workspace_id}/billing/checkout"

    response = client.post(url, json={"plan": "pro", "interval": "year", "return_path": "/projects/abc/billing"}, headers=headers)
    assert response.status_code == 200 and response.json()["url"] == "https://checkout.stripe.test/session"
    sent = fake_stripe.checkouts[-1]
    assert sent["price"] == "price_pro_y" and sent["workspace_id"] == workspace_id
    assert sent["success_url"] == f"{settings.app_base_url}/projects/abc/billing?checkout=success"
    assert billing(client, headers, workspace_id).json()["has_billing_account"] is True

    for bad in ("//evil.com", "https://evil.com", "evil.com"):
        assert client.post(url, json={"plan": "pro", "return_path": bad}, headers=headers).status_code == 422, bad
    assert client.post(url, json={"plan": "enterprise"}, headers=headers).status_code == 422

    portal = client.post(f"{API}/workspaces/{workspace_id}/billing/portal", json={}, headers=headers)
    assert portal.status_code == 200 and portal.json()["url"].startswith("https://billing.stripe.test/cus_")


def test_checkout_without_stripe_configured_says_so(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    headers = signup(client, "nostripe")
    workspace_id = workspace_of(client, headers)
    response = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "pro"}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "BILLING_NOT_CONFIGURED"
    portal = client.post(f"{API}/workspaces/{workspace_id}/billing/portal", json={}, headers=headers)
    assert portal.status_code == 409 and portal.json()["error"]["code"] == "NO_BILLING_ACCOUNT"


def test_webhook_upgrade_flips_the_plan_and_blocks_a_second_checkout(client, fake_stripe):
    headers = signup(client, "upgrade")
    workspace_id = workspace_of(client, headers)
    sub = subscribe(client, fake_stripe, workspace_id, plan_price="price_pro_m")

    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "pro" and body["state"] == "active" and body["interval"] == "month"
    assert body["current_period_end"] is not None and body["has_billing_account"] is True
    with SessionLocal() as session:
        row = session.scalar(select(Subscription).where(Subscription.workspace_id == uuid.UUID(workspace_id)))
        assert row.stripe_subscription_id == sub["id"] and row.stripe_customer_id == sub["customer"]

    again = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "starter"}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_SUBSCRIBED"


def test_duplicate_event_is_ignored(client, fake_stripe):
    headers = signup(client, "dupe")
    workspace_id = workspace_of(client, headers)
    sub = stripe_subscription(workspace_id)
    fake_stripe.subscriptions[sub["id"]] = sub
    event_id = f"evt_{uuid.uuid4().hex}"
    first = post_event(client, "customer.subscription.created", sub, event_id=event_id)
    second = post_event(client, "customer.subscription.created", sub, event_id=event_id)
    assert first.json()["result"] == "applied" and second.json()["result"] == "duplicate"
    assert fake_stripe.retrieved.count(sub["id"]) == 1
    with SessionLocal() as session:
        assert session.get(StripeEvent, event_id).type == "customer.subscription.created"


def test_bad_or_missing_signature_is_rejected(client, fake_stripe):
    assert post_event(client, "customer.subscription.updated", {"id": "sub_x"}, secret="whsec_wrong").status_code == 400
    unsigned = client.post("/api/v1/billing/webhook", content=json.dumps({"id": "evt_x", "type": "x", "data": {"object": {}}}))
    assert unsigned.status_code == 400 and unsigned.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert fake_stripe.retrieved == []


def test_unrelated_event_is_recorded_and_ignored(client, fake_stripe):
    assert post_event(client, "customer.created", {"id": "cus_new"}).json()["result"] == "ignored"


def test_payment_failed_gives_a_grace_period_then_lapses(client, fake_stripe, outbox):
    headers = signup(client, "pastdue")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    sub = subscribe(client, fake_stripe, workspace_id)

    fake_stripe.subscriptions[sub["id"]]["status"] = "past_due"
    invoice = {"object": "invoice", "parent": {"subscription_details": {"subscription": sub["id"]}}}
    assert post_event(client, "invoice.payment_failed", invoice).json()["result"] == "applied"
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "past_due" and body["can_write"] is True
    grace = datetime.fromisoformat(body["grace_ends_at"]) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < grace <= timedelta(days=7)
    assert outbox and outbox[-1][1] == "Your payment failed"

    set_subscription(workspace_id, grace_ends_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "lapsed" and body["can_write"] is False
    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "SUBSCRIPTION_INACTIVE" and blocked.json()["error"]["limit"] == "subscription"
    assert client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).status_code == 200  # still readable

    fake_stripe.subscriptions[sub["id"]]["status"] = "active"  # the card was updated and the retry paid
    assert post_event(client, "invoice.paid", {"object": "invoice", "subscription": sub["id"]}).json()["result"] == "applied"
    body = billing(client, headers, workspace_id).json()
    assert body["state"] == "active" and body["grace_ends_at"] is None


def test_canceled_subscription_lapses_and_a_late_event_cannot_undo_a_newer_one(client, fake_stripe):
    headers = signup(client, "cancel")
    workspace_id = workspace_of(client, headers)
    old = subscribe(client, fake_stripe, workspace_id)
    fake_stripe.subscriptions[old["id"]]["status"] = "canceled"
    post_event(client, "customer.subscription.deleted", old)
    assert billing(client, headers, workspace_id).json()["state"] == "lapsed"

    new = subscribe(client, fake_stripe, workspace_id, plan_price="price_pro_y")
    post_event(client, "customer.subscription.deleted", old)  # redelivered late, different event id
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "pro" and body["state"] == "active"
    with SessionLocal() as session:
        current = session.scalar(select(Subscription.stripe_subscription_id).where(Subscription.workspace_id == uuid.UUID(workspace_id)))
    assert current == new["id"]


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


def test_starter_limits_are_enforced(client, fake_stripe):
    headers = signup(client, "starter")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)  # two competitors
    subscribe(client, fake_stripe, workspace_id)
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
    assert scan["total_runs"] == len(V1_MODELS)  # every engine on every plan

    with SessionLocal() as session:  # one more scan today fills Starter's two; 29 more prompts fill 30
        session.add(Scan(project_id=pid, status="completed"))
        session.add_all([Prompt(project_id=pid, text=f"prompt {i}", category="CATEGORY", intent="DISCOVERY", source="user") for i in range(29)])
        session.commit()
    assert error(client.post(f"{API}/projects/{project_id}/scans", headers=headers)) == (429, "SCAN_LIMIT_REACHED", "scans_per_day")
    extra = client.post(f"{API}/projects/{project_id}/prompts", json={**prompt, "text": "one too many"}, headers=headers)
    assert error(extra) == (409, "PROMPT_LIMIT", "active_prompts")

    usage = billing(client, headers, workspace_id).json()["usage"]
    assert usage["projects"] == 2 and usage["seats"] == 6 and usage["scans_today"] == 2 and usage["active_prompts"] == 30
    first = next(p for p in usage["per_project"] if p["id"] == project_id)
    assert first["competitors"] == 20 and first["active_prompts"] == 30


def test_monthly_answer_cap_refuses_a_scan_that_would_go_over(client, fake_stripe):
    headers = signup(client, "answers")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_stripe, workspace_id)  # Starter: 520 answers in any 30 days
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    client.post(f"{API}/projects/{project_id}/prompts", json=prompt, headers=headers)
    needed = len(V1_MODELS)  # one prompt on every engine
    with SessionLocal() as session:  # older scans (not today, so the daily guard stays out of it)
        old = Scan(project_id=uuid.UUID(project_id), status="completed", total_runs=520 - needed + 1,
                   created_at=datetime.now(timezone.utc) - timedelta(days=3))
        session.add(old)
        session.commit()
        old_id = old.id

    blocked = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert blocked.status_code == 402 and blocked.json()["error"]["limit"] == "answers_per_month"
    assert billing(client, headers, workspace_id).json()["usage"]["answers_30_days"] == 520 - needed + 1

    with SessionLocal() as session:  # a month later those answers no longer count
        session.execute(update(Scan).where(Scan.id == old_id).values(created_at=datetime.now(timezone.utc) - timedelta(days=31)))
        session.commit()
    allowed = client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    assert allowed.status_code == 200 and allowed.json()["total_runs"] == needed


def test_prompt_pool_is_shared_by_every_project(client, fake_stripe):
    headers = signup(client, "pool")
    workspace_id = workspace_of(client, headers)
    first = make_project(client, headers)
    subscribe(client, fake_stripe, workspace_id)  # Starter: 30 prompts in total
    second = client.post(f"{API}/projects", json=PROJECT, headers=headers).json()["id"]
    with SessionLocal() as session:
        session.add_all([Prompt(project_id=uuid.UUID(first), text=f"prompt {i}", category="CATEGORY",
                                intent="DISCOVERY", source="user") for i in range(30)])
        session.commit()
    prompt = {"text": "best crm for startups", "category": "CATEGORY", "intent": "DISCOVERY"}
    refused = client.post(f"{API}/projects/{second}/prompts", json=prompt, headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["limit"] == "active_prompts"
    generated = client.post(f"{API}/projects/{second}/prompts/generate", headers=headers).json()
    assert generated["created"] > 0 and not any(p["is_active"] for p in generated["prompts"])  # kept for review


def test_growth_checkout_and_limits(client, fake_stripe):
    headers = signup(client, "growth")
    workspace_id = workspace_of(client, headers)
    response = client.post(f"{API}/workspaces/{workspace_id}/billing/checkout", json={"plan": "growth", "interval": "year"}, headers=headers)
    assert response.status_code == 200 and fake_stripe.checkouts[-1]["price"] == "price_growth_y"
    subscribe(client, fake_stripe, workspace_id, plan_price="price_growth_m")
    body = billing(client, headers, workspace_id).json()
    assert body["plan"] == "growth" and body["limits"]["projects"] == 4 and body["limits"]["schedules"] is True


def test_pro_allows_what_starter_does_not(client, fake_stripe):
    headers = signup(client, "pro")
    workspace_id = workspace_of(client, headers)
    project_id = make_project(client, headers)
    subscribe(client, fake_stripe, workspace_id, plan_price="price_pro_m")
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


def test_retention_follows_each_workspaces_plan(client, fake_stripe):
    def scanned(prefix):
        headers = signup(client, prefix)
        project_id = make_project(client, headers)
        client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
        scan_id = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()["id"]
        return workspace_of(client, headers), scan_id

    starter_ws, starter_scan = scanned("retstarter")
    subscribe(client, fake_stripe, starter_ws)
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
