"""scan and report cost totals

Revision ID: b2d6e8f14c51
Revises: a1c5d7e93b40
Create Date: 2026-11-01 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2d6e8f14c51'
down_revision: Union[str, Sequence[str], None] = 'a1c5d7e93b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("cost_usd", sa.Numeric(12, 6), server_default=sa.text("0"), nullable=False))
    op.add_column("scans", sa.Column("ai_calls", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("scans", sa.Column("web_searches", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("reports", sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "cost_usd")
    op.drop_column("scans", "web_searches")
    op.drop_column("scans", "ai_calls")
    op.drop_column("scans", "cost_usd")
