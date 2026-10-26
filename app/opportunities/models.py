from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base

OPPORTUNITY_TYPES = (
    "CONTENT_GAP",
    "CITATION_GAP",
    "COMPETITOR_GAP",
    "POSITIONING_GAP",
    "COMPARISON_GAP",
    "ENTITY_GAP",
    "TECHNICAL_GAP",
)
OPPORTUNITY_STATUSES = ("open", "in_progress", "completed", "dismissed")
# new: first seen this scan; open: same as last scan; better/worse: fewer/more prompts affected; resolved: gone this scan.
OPPORTUNITY_TRENDS = ("new", "open", "better", "worse", "resolved")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunities_project_created", "project_id", "created_at"),)  # PRD 87

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    # The same gap across scans shares a fingerprint, so its status and history carry forward (see service.py).
    fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    trend: Mapped[str] = mapped_column(String(20), nullable=False, default="new", server_default="new")  # OPPORTUNITY_TRENDS
    first_seen_scan_id: Mapped[int | None] = mapped_column(nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
