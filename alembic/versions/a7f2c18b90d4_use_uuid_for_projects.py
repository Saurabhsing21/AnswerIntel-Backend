"""use uuid primary keys for projects

Revision ID: a7f2c18b90d4
Revises: c3a91d4e8b12
Create Date: 2026-10-04 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f2c18b90d4"
down_revision: Union[str, Sequence[str], None] = "c3a91d4e8b12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "competitors_project_id_fkey",
        "competitors",
        type_="foreignkey",
    )
    op.drop_index("ix_competitors_project_id", table_name="competitors")

    op.add_column("projects", sa.Column("id_uuid", sa.Uuid(), nullable=True))
    op.execute("UPDATE projects SET id_uuid = gen_random_uuid()")
    op.alter_column("projects", "id_uuid", nullable=False)

    op.add_column("competitors", sa.Column("project_id_uuid", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE competitors AS c
        SET project_id_uuid = p.id_uuid
        FROM projects AS p
        WHERE c.project_id = p.id
        """
    )

    op.drop_column("competitors", "project_id")
    op.drop_constraint("projects_pkey", "projects", type_="primary")
    op.drop_column("projects", "id")

    op.alter_column("projects", "id_uuid", new_column_name="id")
    op.create_primary_key("projects_pkey", "projects", ["id"])

    op.alter_column("competitors", "project_id_uuid", new_column_name="project_id")
    op.alter_column(
        "competitors",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_index(
        "ix_competitors_project_id",
        "competitors",
        ["project_id"],
        unique=False,
    )
    op.create_foreign_key(
        "competitors_project_id_fkey",
        "competitors",
        "projects",
        ["project_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "competitors_project_id_fkey",
        "competitors",
        type_="foreignkey",
    )
    op.drop_index("ix_competitors_project_id", table_name="competitors")

    op.add_column("projects", sa.Column("id_int", sa.Integer(), nullable=True))
    op.execute("CREATE SEQUENCE IF NOT EXISTS projects_id_seq")
    op.execute("UPDATE projects SET id_int = nextval('projects_id_seq')")
    op.alter_column("projects", "id_int", nullable=False)

    op.add_column("competitors", sa.Column("project_id_int", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE competitors AS c
        SET project_id_int = p.id_int
        FROM projects AS p
        WHERE c.project_id = p.id
        """
    )

    op.drop_column("competitors", "project_id")
    op.drop_constraint("projects_pkey", "projects", type_="primary")
    op.drop_column("projects", "id")

    op.alter_column("projects", "id_int", new_column_name="id")
    op.create_primary_key("projects_pkey", "projects", ["id"])
    op.execute("ALTER SEQUENCE projects_id_seq OWNED BY projects.id")
    op.execute(
        "ALTER TABLE projects ALTER COLUMN id SET DEFAULT nextval('projects_id_seq')"
    )

    op.alter_column("competitors", "project_id_int", new_column_name="project_id")
    op.alter_column(
        "competitors",
        "project_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "ix_competitors_project_id",
        "competitors",
        ["project_id"],
        unique=False,
    )
    op.create_foreign_key(
        "competitors_project_id_fkey",
        "competitors",
        "projects",
        ["project_id"],
        ["id"],
    )
