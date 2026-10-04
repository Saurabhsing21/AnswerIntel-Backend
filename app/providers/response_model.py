from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class AIResponseRecord(Base):
    __tablename__ = "ai_responses"

    id: Mapped[int] = mapped_column(primary_key=True)

    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id"),
        nullable=False,
        index=True,
    )

    scan_prompt_id: Mapped[int] = mapped_column(
        ForeignKey("scan_prompts.id"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    response_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    raw_response: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )