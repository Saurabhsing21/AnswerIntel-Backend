from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class FreeCheck(Base):
    """A free, one-off AI visibility snapshot from the website: a few prompts on two engines, no account."""

    __tablename__ = "free_checks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str] = mapped_column(String(500), nullable=False, index=True)  # normalized host
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")  # queued | running | done | failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    client: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # hashed IP, never the raw address
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
