"""index ai_calls.created_at for the daily budget query

Revision ID: c3e7f9a25d62
Revises: b2d6e8f14c51
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c3e7f9a25d62'
down_revision: Union[str, Sequence[str], None] = 'b2d6e8f14c51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_ai_calls_created_at", "ai_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_calls_created_at", table_name="ai_calls")
