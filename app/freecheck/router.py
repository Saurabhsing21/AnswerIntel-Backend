import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.common.config import settings
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.freecheck.models import FreeCheck
from app.freecheck.service import run_free_check

router = APIRouter(prefix="/free-check", tags=["Free check"])


class FreeCheckRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=120)
    website: str = Field(min_length=3, max_length=300)
    category: str = Field(min_length=2, max_length=120)
    country: str = Field(default="United States", max_length=80)

    @field_validator("brand_name", "category", "country")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("website")
    @classmethod
    def host(cls, value: str) -> str:
        value = value.strip().lower()
        parsed = urlparse(value if "://" in value else f"https://{value}")
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("Enter your website, e.g. halden.co")
        return parsed.hostname.removeprefix("www.")


def _client(request: Request) -> str:
    # Behind the website's server route the first forwarded address is the visitor. It can be spoofed, so the
    # global daily cap, not this, is what bounds cost.
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
    return hashlib.sha256(f"{settings.jwt_secret_key}:{ip}".encode()).hexdigest()


def serialize(check: FreeCheck) -> dict:
    return {
        "id": str(check.id), "status": check.status, "brand_name": check.brand_name, "website": check.website,
        "category": check.category, "country": check.country, "result": check.result,
    }


@router.post("")
def start_free_check(payload: FreeCheckRequest, request: Request, background_tasks: BackgroundTasks):
    since = datetime.now(timezone.utc) - timedelta(days=1)
    client = _client(request)
    with SessionLocal() as session:
        recent = session.scalar(
            select(FreeCheck).where(FreeCheck.website == payload.website, FreeCheck.created_at >= since, FreeCheck.status != "failed")
            .order_by(FreeCheck.created_at.desc())
        )
        if recent:  # the same site checked today gets today's result, at no extra cost
            return serialize(recent)
        today = session.scalar(select(func.count()).select_from(FreeCheck).where(FreeCheck.created_at >= since)) or 0
        if today >= settings.free_checks_per_day:
            raise AppError(429, "FREE_CHECK_LIMIT", "We've run all of today's free checks. Try again tomorrow, or pick a plan for a full report.")
        mine = session.scalar(select(func.count()).select_from(FreeCheck).where(FreeCheck.client == client, FreeCheck.created_at >= since)) or 0
        if mine >= settings.free_checks_per_client:
            raise AppError(429, "FREE_CHECK_LIMIT", "You've used today's free checks. Pick a plan to track every prompt, every week.")
        check = FreeCheck(**payload.model_dump(), client=client, status="queued")
        session.add(check)
        session.commit()
        session.refresh(check)
        background_tasks.add_task(run_free_check, check.id)
        return serialize(check)


@router.get("/{check_id}")
def get_free_check(check_id: UUID):
    with SessionLocal() as session:
        check = session.get(FreeCheck, check_id)
        if not check:
            raise AppError(404, "FREE_CHECK_NOT_FOUND", "Free check not found.")
        return serialize(check)
