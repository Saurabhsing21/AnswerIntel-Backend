from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class ScanPrompt(Base):
    __tablename__ = "scan_prompts"

    id: Mapped[int] = mapped_column(primary_key=True)

    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    intent: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "text",
            name="uq_scan_prompt_text",
        ),
    )