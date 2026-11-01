"""add mentions.other_brands: recommended brands the project does not track

Revision ID: e5b2c7d91f40
Revises: d4a8b1c63e07
Create Date: 2026-11-01 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5b2c7d91f40'
down_revision: Union[str, Sequence[str], None] = 'd4a8b1c63e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("other_brands", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("mentions", "other_brands")
