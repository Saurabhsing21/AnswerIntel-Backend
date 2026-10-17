import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from app.api.router import router as api_router
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


app = FastAPI(title="AnswerIntel API", lifespan=lifespan)

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


@app.get("/health")
def health_check():
    return {"status": "ok", "ai_enabled": settings.ai_enabled}


@app.get("/ready")
def ready():
    checks, ok = observability.readiness()
    return JSONResponse({"status": "ready" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)
