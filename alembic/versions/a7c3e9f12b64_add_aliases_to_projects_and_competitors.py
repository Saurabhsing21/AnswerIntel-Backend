"""add aliases: other names for the brand and for each competitor

Revision ID: a7c3e9f12b64
Revises: c1e5a7d93f42
Create Date: 2026-11-08 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c3e9f12b64'
down_revision: Union[str, Sequence[str], None] = 'c1e5a7d93f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("competitors", sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("competitors", "aliases")
    op.drop_column("projects", "aliases")
