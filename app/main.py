import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from app.api.router import router as api_router
from app.billing.webhook import router as billing_webhook_router
from app.common import observability
from app.common.config import settings
from app.common.errors import register_error_handlers

observability.configure_logging()
observability.init_sentry()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.scans.execution import recover_interrupted_scans

    # With a queue, unacknowledged scan jobs are redelivered and resume; only in-process scans are lost on restart.
    if not settings.redis_url:
        try:
            recovered = recover_interrupted_scans()
            if recovered:
                log.warning("Marked %s interrupted scan(s) as failed/partial", recovered)
        except Exception:  # database may be unavailable at boot; health check will show it
            log.exception("Could not recover interrupted scans")
    yield


# No public API docs in production or while only the waitlist is open.
_hide_docs = settings.app_env == "production" or settings.waitlist_only
app = FastAPI(
    title="SeenLens API",
    lifespan=lifespan,
    docs_url=None if _hide_docs else "/docs",
    redoc_url=None if _hide_docs else "/redoc",
    openapi_url=None if _hide_docs else "/openapi.json",
)

# While only the waitlist is open, every other API route answers 404 (health checks stay up).
WAITLIST_ONLY_OPEN = {"/api/v1/waitlist"}


@app.middleware("http")
async def waitlist_only_gate(request: Request, call_next):
    if settings.waitlist_only and request.url.path.startswith("/api/") and request.url.path not in WAITLIST_ONLY_OPEN:
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": "Not found."}, "detail": "Not found."})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
observability.install(app)
app.include_router(api_router)
app.include_router(billing_webhook_router)  # no user and no per-IP limit: Stripe signs every call


@app.get("/health")
def health_check():
    return {"status": "ok", "ai_enabled": settings.ai_enabled}


@app.get("/ready")
def ready():
    checks, ok = observability.readiness()
    return JSONResponse({"status": "ready" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)
