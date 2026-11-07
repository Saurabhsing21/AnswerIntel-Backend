"""add refresh_tokens.replaced_by_id: the token a rotation replaced it with (reuse grace window)

Revision ID: a7c3e9f21b56
Revises: e5b2c7d91f40
Create Date: 2026-11-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c3e9f21b56'
down_revision: Union[str, Sequence[str], None] = 'e5b2c7d91f40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("replaced_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "refresh_tokens_replaced_by_id_fkey", "refresh_tokens", "refresh_tokens", ["replaced_by_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("refresh_tokens_replaced_by_id_fkey", "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "replaced_by_id")
