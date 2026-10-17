from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class ScanSchedule(Base):
    """Weekly re-scan for a project (PRD 82). Times are UTC; day_of_week 0 = Monday."""

    __tablename__ = "scan_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="weekly", server_default="weekly")
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=9, server_default="9")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Slots before this moment never fire, so enabling a schedule cannot trigger a back-dated scan.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
