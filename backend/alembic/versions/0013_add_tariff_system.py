"""add tariff system

Revision ID: 0013
Revises: 0012
Create Date: 2024-10-12 05:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = inspector.get_table_names()
    if "tariffs" not in tables:
        op.create_table(
            "tariffs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=64), nullable=False, unique=True),
            sa.Column("max_accounts", sa.Integer(), nullable=False),
            sa.Column("max_invites_day", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.bulk_insert(
            sa.table(
                "tariffs",
                sa.column("id", sa.Integer()),
                sa.column("name", sa.String()),
                sa.column("max_accounts", sa.Integer()),
                sa.column("max_invites_day", sa.Integer()),
                sa.column("price", sa.Float()),
            ),
            [
                {"id": 1, "name": "Free", "max_accounts": 5, "max_invites_day": 50, "price": None},
                {"id": 2, "name": "Pro", "max_accounts": 20, "max_invites_day": 200, "price": None},
            ],
        )

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "tariff_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "tariff_id",
                sa.Integer(),
                sa.ForeignKey("tariffs.id"),
                nullable=False,
                server_default="1",
            ),
        )
        op.alter_column("users", "tariff_id", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "tariff_id" in user_columns:
        op.drop_column("users", "tariff_id")

    tables = inspector.get_table_names()
    if "tariffs" in tables:
        op.drop_table("tariffs")
