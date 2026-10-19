from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class Subscription(Base):
    """One per workspace. Stripe owns prices and payment state; this row mirrors it, and app/billing/plans.py
    turns it into limits. Written only by signup/workspace creation (trial) and the Stripe webhook."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # trial | starter | pro
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)  # month | year; none on a trial
    # Stripe's subscription status (active, past_due, canceled, unpaid, ...) or "trialing" for the card-free trial.
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Set when a payment first fails; writes keep working until then, after that the workspace is read-only.
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last trial email sent (trial_ending, trial_ended), so the daily job never sends one twice.
    notified: Mapped[str | None] = mapped_column(String(30), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StripeEvent(Base):
    """Webhook events already handled. Stripe retries and may deliver an event more than once."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
