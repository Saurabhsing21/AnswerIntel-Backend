"""switch billing from stripe to cashfree

Stripe only ever ran in test mode, so its ids are dropped rather than carried over.

Revision ID: b3d8f1a6c2e9
Revises: a7c3e9f12b64
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b3d8f1a6c2e9'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f12b64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("subscriptions", "stripe_customer_id")
    op.drop_column("subscriptions", "stripe_subscription_id")
    op.add_column("subscriptions", sa.Column("cashfree_subscription_id", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("billing_phone", sa.String(length=20), nullable=True))
    op.add_column("subscriptions", sa.Column("cashfree_pending_id", sa.String(length=255), nullable=True))
    op.create_unique_constraint("subscriptions_cashfree_subscription_id_key", "subscriptions", ["cashfree_subscription_id"])
    op.rename_table("stripe_events", "billing_events")
    op.execute("ALTER INDEX stripe_events_pkey RENAME TO billing_events_pkey")


def downgrade() -> None:
    op.execute("ALTER INDEX billing_events_pkey RENAME TO stripe_events_pkey")
    op.rename_table("billing_events", "stripe_events")
    op.drop_constraint("subscriptions_cashfree_subscription_id_key", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "cashfree_pending_id")
    op.drop_column("subscriptions", "billing_phone")
    op.drop_column("subscriptions", "cashfree_subscription_id")
    op.add_column("subscriptions", sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("stripe_customer_id", sa.String(length=255), nullable=True))
    op.create_unique_constraint("subscriptions_stripe_subscription_id_key", "subscriptions", ["stripe_subscription_id"])
    op.create_unique_constraint("subscriptions_stripe_customer_id_key", "subscriptions", ["stripe_customer_id"])
