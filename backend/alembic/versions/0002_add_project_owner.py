"""add project owner

Revision ID: 0002
Revises: 0001
Create Date: 2024-10-11 00:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("projects")}

    if "owner_id" not in columns:
        op.add_column("projects", sa.Column("owner_id", sa.Integer(), nullable=False))
        op.create_foreign_key(
            "fk_projects_owner_id_users", "projects", "users", ["owner_id"], ["id"]
        )
        op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("projects")}

    if "owner_id" in columns:
        op.drop_index("ix_projects_owner_id", table_name="projects")
        op.drop_constraint("fk_projects_owner_id_users", "projects", type_="foreignkey")
        op.drop_column("projects", "owner_id")
