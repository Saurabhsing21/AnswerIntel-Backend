"""scan_prompts.ask_number: a re-test asks each prompt several times, one row per ask

Revision ID: c1e5a7d93f42
Revises: b8d4f2a6c913
Create Date: 2026-11-08 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c1e5a7d93f42'
down_revision: Union[str, Sequence[str], None] = 'b8d4f2a6c913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scan_prompts", sa.Column("ask_number", sa.Integer(), server_default="1", nullable=False))
    op.drop_constraint("uq_scan_prompt_text", "scan_prompts", type_="unique")
    op.create_unique_constraint("uq_scan_prompt_text", "scan_prompts", ["scan_id", "text", "ask_number"])


def downgrade() -> None:
    op.execute("DELETE FROM scan_prompts WHERE ask_number > 1")
    op.drop_constraint("uq_scan_prompt_text", "scan_prompts", type_="unique")
    op.create_unique_constraint("uq_scan_prompt_text", "scan_prompts", ["scan_id", "text"])
    op.drop_column("scan_prompts", "ask_number")
