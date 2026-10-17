from datetime import date, datetime
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base

REPORT_TYPES = ("weekly", "monthly", "manual")
PERIOD_DAYS = {"weekly": 7, "monthly": 30, "manual": 7}


class Report(Base):
    """A frozen founder report (PRD 43). Content is a snapshot; later scans never change it."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready", server_default="ready")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
