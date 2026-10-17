"""Logging, request ids, security headers, readiness and error monitoring (PRD 63, 65).

Never logged: passwords, tokens, API keys, headers, request or response bodies, query strings.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from sqlalchemy import text

from app.common.config import settings
from app.common.database import engine

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
access_log = logging.getLogger("answerintel.access")

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in data:
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging() -> None:
    # httpx logs every outbound URL at INFO, including user-supplied ones and any query-string secrets.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return  # already configured (reloads, tests)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, send_default_pii=False, traces_sample_rate=0.0)


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))


def check_redis() -> None:
    import redis

    redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()


def readiness() -> tuple[dict, bool]:
    """Dependency checks for load balancers. Only 'ok' / 'failed' / 'skipped': no error details leave the process."""
    checks: dict[str, str] = {}
    for name, check, enabled in (("database", check_database, True), ("redis", check_redis, bool(settings.redis_url))):
        if not enabled:
            checks[name] = "skipped"
            continue
        try:
            check()
            checks[name] = "ok"
        except Exception:
            logging.getLogger(__name__).exception("Readiness check failed: %s", name)
            checks[name] = "failed"
    return checks, "failed" not in checks.values()


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            access_log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,  # no query string: it can carry tokens
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id": request_id,
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
