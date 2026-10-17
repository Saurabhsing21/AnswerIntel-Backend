from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base

EXPERIMENT_STATUSES = ("running", "completed")
SNAPSHOT_KINDS = ("baseline", "after")


class Experiment(Base):
    """A tracked change: baseline scan -> change shipped -> follow-up scan -> compare (PRD 41)."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExperimentSnapshot(Base):
    """Metrics frozen at baseline and at completion; later scans never change them (PRD 42)."""

    __tablename__ = "experiment_snapshots"
    __table_args__ = (UniqueConstraint("experiment_id", "kind", name="uq_experiment_snapshot_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    mention_rate: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    share_of_voice: Mapped[float] = mapped_column(Float, nullable=False)
    average_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
