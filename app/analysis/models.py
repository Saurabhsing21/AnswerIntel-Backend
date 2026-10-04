from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(primary_key=True)

    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id"),
        nullable=False,
        index=True,
    )

    brand_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    mentioned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    recommended: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    position: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    sentiment: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CompetitorObservation(Base):
    __tablename__ = "competitor_observations"

    id: Mapped[int] = mapped_column(primary_key=True)

    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id"),
        nullable=False,
        index=True,
    )

    competitor_id: Mapped[int] = mapped_column(
        ForeignKey("competitors.id"),
        nullable=False,
        index=True,
    )

    mentioned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    position: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    sentiment: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)

    ai_response_id: Mapped[int] = mapped_column(
        ForeignKey("ai_responses.id"),
        nullable=False,
        index=True,
    )

    url: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    source_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )