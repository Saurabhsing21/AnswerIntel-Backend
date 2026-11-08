"""add scans.credits: what each scan was charged against the plan's 30-day credit cap

Revision ID: b8d4f2a6c913
Revises: a7c3e9f21b56
Create Date: 2026-11-08 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b8d4f2a6c913'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f21b56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Before credits every answer counted as one, so older scans keep the usage they already had.
BACKFILL_CREDITS = "UPDATE scans SET credits = total_runs"


def upgrade() -> None:
    op.add_column("scans", sa.Column("credits", sa.Numeric(10, 2), server_default="0", nullable=False))
    op.execute(BACKFILL_CREDITS)


def downgrade() -> None:
    op.drop_column("scans", "credits")
