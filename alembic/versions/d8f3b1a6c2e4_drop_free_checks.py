"""drop free checks: the no-account website check is gone; new accounts get one free scan instead

Revision ID: d8f3b1a6c2e4
Revises: c4e9a2b7d5f1
Create Date: 2026-11-17 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f3b1a6c2e4'
down_revision: Union[str, Sequence[str], None] = 'c4e9a2b7d5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_free_checks_website'), table_name='free_checks')
    op.drop_index(op.f('ix_free_checks_created_at'), table_name='free_checks')
    op.drop_index(op.f('ix_free_checks_client'), table_name='free_checks')
    op.drop_table('free_checks')


def downgrade() -> None:
    op.create_table('free_checks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('brand_name', sa.String(length=255), nullable=False),
    sa.Column('website', sa.String(length=500), nullable=False),
    sa.Column('category', sa.String(length=255), nullable=False),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('client', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_free_checks_client'), 'free_checks', ['client'], unique=False)
    op.create_index(op.f('ix_free_checks_created_at'), 'free_checks', ['created_at'], unique=False)
    op.create_index(op.f('ix_free_checks_website'), 'free_checks', ['website'], unique=False)
