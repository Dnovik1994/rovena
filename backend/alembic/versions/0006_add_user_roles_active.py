"""add user role and active

Revision ID: 0006
Revises: 0005
Create Date: 2024-10-11 01:25:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        columns = set()
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = {column["name"] for column in inspector.get_columns("users")}

    if "is_active" not in columns:
        op.add_column(
            "users",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
        op.alter_column("users", "is_active", server_default=None)

    if "role" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "role",
                sa.Enum("user", "admin", "superadmin", name="userrole"),
                nullable=False,
                server_default="user",
            ),
        )
        op.alter_column("users", "role", server_default=None)


def downgrade() -> None:
    if context.is_offline_mode():
        columns = {"role", "is_active"}
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = {column["name"] for column in inspector.get_columns("users")}

    if "role" in columns:
        op.drop_column("users", "role")
        # MySQL auto-drops ENUM with column, no separate DROP TYPE needed
    if "is_active" in columns:
        op.drop_column("users", "is_active")
