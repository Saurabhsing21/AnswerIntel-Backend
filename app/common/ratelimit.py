"""Fixed-window rate limiting (PRD 60). Shared via Redis when configured, per-process memory otherwise."""

import logging
import threading
import time

from fastapi import Request

from app.auth.jwt import decode_access_token
from app.common.config import settings
from app.common.errors import AppError

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._client = None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _redis(self):
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(settings.redis_url, socket_timeout=1)
        return self._client

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        if not settings.rate_limit_enabled:
            return True
        if settings.redis_url:
            try:
                client = self._redis()
                count = client.incr(f"rl:{key}")
                if count == 1:
                    client.expire(f"rl:{key}", window)
                return count <= limit
            except Exception:
                # Fail open: losing protection briefly beats taking the whole API down with Redis.
                log.warning("Rate limiter could not reach Redis; allowing the request", exc_info=True)
                return True
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v[1] > now}
            count, expires = self._hits.get(key, (0, 0.0))
            if expires <= now:
                count, expires = 0, now + window
            count += 1
            self._hits[key] = (count, expires)
            return count <= limit


limiter = RateLimiter()


def _client_ip(request: Request) -> str:
    # Behind a proxy, run uvicorn with --proxy-headers so this is the real client address.
    return request.client.host if request.client else "unknown"


def limit_login(request: Request) -> None:
    if not limiter.allow(f"login:{_client_ip(request)}", settings.login_rate_limit_per_minute):
        raise AppError(429, "RATE_LIMITED", "Too many login attempts. Please wait a minute and try again.")


def limit_waitlist(request: Request) -> None:
    if not limiter.allow(f"waitlist:{_client_ip(request)}", settings.waitlist_rate_limit_per_minute):
        raise AppError(429, "RATE_LIMITED", "Too many requests. Please try again in a minute.")


def limit_api(request: Request) -> None:
    who = _client_ip(request)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            who = f"user:{decode_access_token(token)}"
        except ValueError:
            pass  # a bad token is rejected by the route itself; limit it by IP
    if not limiter.allow(f"api:{who}", settings.api_rate_limit_per_minute):
        raise AppError(429, "RATE_LIMITED", "Too many requests. Please slow down.")
