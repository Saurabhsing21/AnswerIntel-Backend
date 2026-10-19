from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_feature
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.schedules.models import ScanSchedule
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/schedule", tags=["Schedule"])


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)  # 0 = Monday, UTC
    hour: int | None = Field(default=None, ge=0, le=23)  # UTC


def serialize(schedule: ScanSchedule | None) -> dict:
    if not schedule:
        return {"enabled": False, "frequency": "weekly", "day_of_week": 0, "hour": 9, "last_run_at": None}
    return {
        "enabled": schedule.enabled,
        "frequency": schedule.frequency,
        "day_of_week": schedule.day_of_week,
        "hour": schedule.hour,
        "last_run_at": schedule.last_run_at,
    }


@router.get("")
def get_schedule(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        return serialize(session.scalar(select(ScanSchedule).where(ScanSchedule.project_id == project.id)))


@router.put("")
def update_schedule(project_id: UUID, payload: ScheduleUpdate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        if payload.enabled:
            require_feature(entitlements(session, project.workspace_id), "schedules", "Weekly schedules")
        schedule = session.scalar(select(ScanSchedule).where(ScanSchedule.project_id == project.id))
        if not schedule:
            schedule = ScanSchedule(project_id=project.id, enabled=False, day_of_week=0, hour=9)
            session.add(schedule)
        before = (schedule.enabled, schedule.day_of_week, schedule.hour)
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(schedule, field, value)
        if schedule.enabled and (schedule.enabled, schedule.day_of_week, schedule.hour) != before:
            schedule.starts_at = datetime.now(timezone.utc)  # a new or changed schedule only fires from now on
        session.commit()
        session.refresh(schedule)
        return serialize(schedule)
