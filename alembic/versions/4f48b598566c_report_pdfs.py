"""report pdfs

Revision ID: 4f48b598566c
Revises: 161c942fdea3
Create Date: 2026-10-27 22:05:55.427879

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f48b598566c'
down_revision: Union[str, Sequence[str], None] = '161c942fdea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_pdfs",
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("render_ms", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("report_pdfs")
