from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base

# queued -> running -> completed | partial | failed
ACTIVE_STATUSES = ("queued", "running")


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_project_created", "project_id", "created_at"),)  # PRD 87

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    # "full" = every active prompt; "retest" = only one opportunity's prompts, to check a fix. Retests never feed the
    # dashboard, trends, opportunities or alerts.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="full", server_default="full")
    opportunity_id: Mapped[int | None] = mapped_column(nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
