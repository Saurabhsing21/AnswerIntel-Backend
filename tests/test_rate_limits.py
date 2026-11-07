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
            self.counts, self.expiries, self.queued = {}, {}, []

        def pipeline(self):
            return self

        def set(self, key, value, ex, nx):
            self.queued.append(("set", key, value, ex, nx))

        def incr(self, key):
            self.queued.append(("incr", key))

        def execute(self):
            results = []
            for op, key, *args in self.queued:
                if op == "set":
                    value, ex, _ = args
                    created = key not in self.counts
                    if created:
                        self.counts[key], self.expiries[key] = value, ex
                    results.append(created)
                else:
                    self.counts[key] += 1
                    results.append(self.counts[key])
            self.queued = []
            return results

    fake = FakeRedis()
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit.limiter, "_redis", lambda: fake)
    assert [ratelimit.limiter.allow("k", 2, 60) for _ in range(3)] == [True, True, False]
    assert fake.expiries == {"rl:k": 60}  # the window is set once, together with the counter


def test_a_broken_redis_does_not_take_the_api_down(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(ratelimit.limiter, "_redis", broken)
    assert ratelimit.limiter.allow("k", 1, 60) is True  # fail open: protection is lost, availability is not


def test_account_deletion_guesses_are_limited(client):
    headers = signup(client, "ratedel")
    statuses = [client.request("DELETE", f"{API}/auth/me", json={"password": "wrong-password"}, headers=headers).status_code for _ in range(7)]
    assert statuses[:4] == [400] * 4  # signup's own login used one of the five attempts
    assert 429 in statuses and statuses[-1] == 429
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200


def test_visitor_address_from_the_website_counts_per_visitor(client, monkeypatch):
    # Every login reaches the API from the website's server; with the shared secret, each visitor has their own limit.
    monkeypatch.setattr(settings, "proxy_shared_secret", "s3cret")
    body = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong-password"}

    def login(ip):
        return client.post(f"{API}/auth/login", json=body, headers={"X-Proxy-Secret": "s3cret", "X-Client-IP": ip}).status_code

    assert [login("203.0.113.1") for _ in range(6)][-1] == 429
    assert login("203.0.113.2") == 401  # another visitor behind the same website server is unaffected


def test_visitor_address_without_the_secret_is_ignored(client, monkeypatch):
    # Anyone can call the API directly: a made-up address must not buy a fresh limit.
    monkeypatch.setattr(settings, "proxy_shared_secret", "s3cret")
    body = {"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": "wrong-password"}
    statuses = [
        client.post(f"{API}/auth/login", json=body, headers={"X-Proxy-Secret": "wrong", "X-Client-IP": f"198.51.100.{i}"}).status_code
        for i in range(7)
    ]
    assert statuses[5:] == [429, 429]
