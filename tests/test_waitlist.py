"""Landing page waitlist: public, idempotent, does not reveal who already signed up."""

import uuid

from sqlalchemy import func, select

from app.common import ratelimit
from app.common.config import settings
from app.common.database import SessionLocal
from app.waitlist.models import WaitlistSignup
from tests.conftest import API


def rows_for(email: str) -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(WaitlistSignup).where(WaitlistSignup.email == email)) or 0


def fresh_email() -> str:
    return f"wait-{uuid.uuid4().hex}@example.com"


def test_signup_is_stored_normalized(client):
    email = fresh_email()
    response = client.post(f"{API}/waitlist", json={"email": f"  {email.upper()}  "})
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert rows_for(email) == 1  # trimmed and lower-cased


def test_duplicate_signup_looks_identical_and_stores_once(client):
    email = fresh_email()
    first = client.post(f"{API}/waitlist", json={"email": email})
    again = client.post(f"{API}/waitlist", json={"email": email.upper()})
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert rows_for(email) == 1


def test_invalid_email_is_rejected(client):
    for bad in ("not-an-email", "", "a@b", "x" * 300 + "@example.com"):
        response = client.post(f"{API}/waitlist", json={"email": bad})
        assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post(f"{API}/waitlist", json={}).status_code == 422


def test_waitlist_is_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.limiter.reset()
    statuses = [client.post(f"{API}/waitlist", json={"email": fresh_email()}).status_code for _ in range(12)]
    assert statuses[:10] == [200] * 10 and statuses[10:] == [429, 429]
    ratelimit.limiter.reset()
