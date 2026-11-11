"""switch billing from stripe to paddle

Stripe only ever ran in test mode, so its ids are dropped rather than carried over.

Revision ID: c4e9a2b7d5f1
Revises: a7c3e9f12b64
Create Date: 2026-11-11 21:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c4e9a2b7d5f1'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f12b64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("subscriptions", "stripe_customer_id")
    op.drop_column("subscriptions", "stripe_subscription_id")
    op.add_column("subscriptions", sa.Column("paddle_subscription_id", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("paddle_customer_id", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("paddle_price_id", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("paddle_product_id", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("scheduled_change_action", sa.String(length=20), nullable=True))
    op.add_column("subscriptions", sa.Column("scheduled_change_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("paddle_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("subscriptions_paddle_subscription_id_key", "subscriptions", ["paddle_subscription_id"])
    op.create_index("ix_subscriptions_paddle_customer_id", "subscriptions", ["paddle_customer_id"])
    op.create_table(
        "paddle_customers",
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("customer_id"),
    )
    op.rename_table("stripe_events", "billing_events")
    op.execute("ALTER INDEX stripe_events_pkey RENAME TO billing_events_pkey")


def downgrade() -> None:
    op.execute("ALTER INDEX billing_events_pkey RENAME TO stripe_events_pkey")
    op.rename_table("billing_events", "stripe_events")
    op.drop_table("paddle_customers")
    op.drop_index("ix_subscriptions_paddle_customer_id", table_name="subscriptions")
    op.drop_constraint("subscriptions_paddle_subscription_id_key", "subscriptions", type_="unique")
    for column in ("paddle_updated_at", "scheduled_change_at", "scheduled_change_action", "paddle_product_id",
                   "paddle_price_id", "paddle_customer_id", "paddle_subscription_id"):
        op.drop_column("subscriptions", column)
    op.add_column("subscriptions", sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("stripe_customer_id", sa.String(length=255), nullable=True))
    op.create_unique_constraint("subscriptions_stripe_subscription_id_key", "subscriptions", ["stripe_subscription_id"])
    op.create_unique_constraint("subscriptions_stripe_customer_id_key", "subscriptions", ["stripe_customer_id"])
