from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class Subscription(Base):
    """One per workspace. Paddle owns payment state; this row mirrors it from verified webhooks, and
    app/billing/plans.py turns it into limits. Also written by signup/workspace creation (trial) and plan changes."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # trial | starter | pro
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)  # month | year; none on a trial
    # Paddle's subscription status (active, trialing, past_due, paused, canceled), or "none" before the first payment.
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Set when a payment first fails; writes keep working until then, after that the workspace is read-only.
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last trial email sent (trial_ending, trial_ended), so the daily job never sends one twice.
    notified: Mapped[str | None] = mapped_column(String(30), nullable=True)
    paddle_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    paddle_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    paddle_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paddle_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A change Paddle will make later, e.g. cancel at the end of the period. Access holds until it happens.
    scheduled_change_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scheduled_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When Paddle last changed the subscription, so an older event delivered late never overwrites a newer one.
    paddle_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PaddleCustomer(Base):
    """Paddle customers, mirrored from customer.created/updated. A workspace's row points here by paddle_customer_id."""

    __tablename__ = "paddle_customers"

    customer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BillingEvent(Base):
    """Paddle webhook events already handled (by Paddle's event id). Deliveries are at-least-once."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
