from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base

REPORT_TYPES = ("weekly", "monthly", "manual")
PERIOD_DAYS = {"weekly": 7, "monthly": 30, "manual": 7}


class Report(Base):
    """A frozen founder report (PRD 43). Content is a snapshot; later scans never change it."""

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_project_created", "project_id", "created_at"),)  # PRD 87

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
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)  # admin-only: its scan's cost
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReportPdf(Base):
    """A report's PDF, drawn once by the report worker and served from here. Kept apart so listing reports never
    loads the file."""

    __tablename__ = "report_pdfs"

    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending, ready or failed
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)  # set = the file lives in R2, `pdf` is empty
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    render_ms: Mapped[int | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
