from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class MetricSnapshot(Base):
    """Brand metrics for one scan, computed in Python from stored observations."""

    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_responses: Mapped[int] = mapped_column(Integer, nullable=False)
    mention_rate: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    share_of_voice: Mapped[float] = mapped_column(Float, nullable=False)
    citation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    positive_sentiment_rate: Mapped[float] = mapped_column(Float, nullable=False)
    average_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    by_engine: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompetitorMetric(Base):
    __tablename__ = "competitor_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True)
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mention_rate: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    share_of_voice: Mapped[float] = mapped_column(Float, nullable=False)
    average_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
