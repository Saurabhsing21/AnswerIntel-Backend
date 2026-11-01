"""add report_pdfs.storage_key for PDFs kept in R2

Revision ID: d4a8b1c63e07
Revises: c3e7f9a25d62
Create Date: 2026-11-01 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4a8b1c63e07'
down_revision: Union[str, Sequence[str], None] = 'c3e7f9a25d62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("report_pdfs", sa.Column("storage_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("report_pdfs", "storage_key")
