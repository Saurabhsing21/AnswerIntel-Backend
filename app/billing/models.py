from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class Subscription(Base):
    """One per workspace. Cashfree owns payment state; this row mirrors it, and app/billing/plans.py turns it into
    limits. Written by signup/workspace creation (trial), the Cashfree webhook and the owner's cancel/change."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # trial | starter | pro
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)  # month | year; none on a trial
    # Cashfree's subscription status mapped to active, past_due, canceled, paused, incomplete, ... (service.py),
    # or "trialing" for the card-free trial.
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Set when a payment first fails; writes keep working until then, after that the workspace is read-only.
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last trial email sent (trial_ending, trial_ended), so the daily job never sends one twice.
    notified: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cashfree_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # The latest checkout, not yet confirmed: synced from Cashfree when the owner returns, in case a webhook is late.
    cashfree_pending_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Cashfree requires a phone number for every subscription; asked once at the first checkout.
    billing_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BillingEvent(Base):
    """Webhook events already handled. Cashfree retries and may deliver an event more than once; it sends no event
    id, so the id is a hash of the payload."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
