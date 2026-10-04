"""create ai_responses table

Revision ID: b8e4d21c7a55
Revises: 2fc00570db9c
Create Date: 2026-10-04 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4d21c7a55"
down_revision: Union[str, Sequence[str], None] = "2fc00570db9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("scan_prompt_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"]),
        sa.ForeignKeyConstraint(["scan_prompt_id"], ["scan_prompts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_responses_scan_id"),
        "ai_responses",
        ["scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_responses_scan_prompt_id"),
        "ai_responses",
        ["scan_prompt_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_responses_scan_prompt_id"), table_name="ai_responses")
    op.drop_index(op.f("ix_ai_responses_scan_id"), table_name="ai_responses")
    op.drop_table("ai_responses")
