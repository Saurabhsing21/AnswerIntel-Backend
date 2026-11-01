from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class AICall(Base):
    """One billable provider call (an attempt that got a response), with the cost the provider reported."""

    __tablename__ = "ai_calls"
    __table_args__ = (
        Index("ix_ai_calls_workspace_created", "workspace_id", "created_at"),
        Index("ix_ai_calls_project_created", "project_id", "created_at"),
        Index("ix_ai_calls_scan", "scan_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    scan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    ai_response_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK: responses get purged by retention
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    engine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    web_searches: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0, server_default=text("0"))
    cost_source: Mapped[str] = mapped_column(String(20), nullable=False)  # provider | estimated
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | failed
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
