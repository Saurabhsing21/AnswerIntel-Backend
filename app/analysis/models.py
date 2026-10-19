from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class Mention(Base):
    """Structured observation about the project's own brand in one AI response."""

    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    position: Mapped[int | None] = mapped_column(nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # The sentence in the answer behind the verdict, shown highlighted so people see why AI picked a brand.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_method: Mapped[str] = mapped_column(String(20), nullable=False, default="heuristic", server_default="heuristic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CompetitorObservation(Base):
    __tablename__ = "competitor_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    position: Mapped[int | None] = mapped_column(nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_brand_owned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    competitor_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
