"""PRD section 60: login 5/min/IP, general API 100/min/user, Redis-backed when configured."""

import uuid

import pytest

from app.common import ratelimit
from app.common.config import settings
from tests.conftest import API, signup


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.limiter.reset()
    yield
    ratelimit.limiter.reset()


def test_login_is_limited_per_ip(client):
    body = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong-password"}
    statuses = [client.post(f"{API}/auth/login", json=body).status_code for _ in range(7)]
    assert statuses[:5] == [401] * 5  # five wrong guesses are answered normally
    assert statuses[5:] == [429, 429]
    blocked = client.post(f"{API}/auth/login", json=body)
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


def test_api_limit_is_per_user(client, monkeypatch):
    first, second = signup(client, "ratea"), signup(client, "rateb")
    monkeypatch.setattr(settings, "api_rate_limit_per_minute", 3)
    ratelimit.limiter.reset()  # signing up used some of the IP-level budget; start both users clean

    assert [client.get(f"{API}/auth/me", headers=first).status_code for _ in range(3)] == [200, 200, 200]
    assert client.get(f"{API}/auth/me", headers=first).status_code == 429
    assert client.get(f"{API}/auth/me", headers=second).status_code == 200  # another user is unaffected


def test_limits_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    body = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong-password"}
    assert {client.post(f"{API}/auth/login", json=body).status_code for _ in range(8)} == {401}


def test_redis_backend_counts_in_a_shared_store(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.counts, self.expiries = {}, {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, seconds):
            self.expiries[key] = seconds

    fake = FakeRedis()
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit.limiter, "_redis", lambda: fake)
    assert [ratelimit.limiter.allow("k", 2, 60) for _ in range(3)] == [True, True, False]
    assert fake.expiries == {"rl:k": 60}  # the window is set once, on the first hit


def test_a_broken_redis_does_not_take_the_api_down(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit.limiter, "_redis", broken)
    assert ratelimit.limiter.allow("k", 1, 60) is True  # fail open: protection is lost, availability is not
