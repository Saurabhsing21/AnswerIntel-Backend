"""ai_calls ledger

Revision ID: a1c5d7e93b40
Revises: 4f48b598566c
Create Date: 2026-11-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c5d7e93b40'
down_revision: Union[str, Sequence[str], None] = '4f48b598566c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ai_response_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("engine", sa.String(length=50), nullable=True),
        sa.Column("generation_id", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("web_searches", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_ai_calls_workspace_created", "ai_calls", ["workspace_id", "created_at"])
    op.create_index("ix_ai_calls_project_created", "ai_calls", ["project_id", "created_at"])
    op.create_index("ix_ai_calls_scan", "ai_calls", ["scan_id"])


def downgrade() -> None:
    op.drop_table("ai_calls")
