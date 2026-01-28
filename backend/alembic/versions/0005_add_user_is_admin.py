"""add user is_admin

Revision ID: 0005
Revises: 0004
Create Date: 2024-10-11 01:10:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        columns = set()
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = {column["name"] for column in inspector.get_columns("users")}

    if "is_admin" not in columns:
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        op.alter_column("users", "is_admin", server_default=None)


def downgrade() -> None:
    if context.is_offline_mode():
        columns = {"is_admin"}
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = {column["name"] for column in inspector.get_columns("users")}

    if "is_admin" in columns:
        op.drop_column("users", "is_admin")
