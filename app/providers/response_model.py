from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class AIResponseRecord(Base):
    """Raw observation: exactly what an engine said. Never rewritten (PRD section 22)."""

    __tablename__ = "ai_responses"
    # One observation per prompt and engine in a scan: no duplicate provider calls (PRD 58).
    __table_args__ = (UniqueConstraint("scan_id", "scan_prompt_id", "engine", name="uq_ai_response_observation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scan_prompt_id: Mapped[int] = mapped_column(
        ForeignKey("scan_prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSON, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True  # retention purge scans by age
    )
