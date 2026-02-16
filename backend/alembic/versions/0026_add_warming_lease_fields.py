"""Add warming lease fields to telegram_accounts.

Adds warming_task_id and warming_task_started_at for warming lease mechanism
to prevent race conditions in concurrent warming tasks.

Revision ID: 0026_add_warming_lease_fields
Revises: 0025_add_warming_channels_and_joined_field
Create Date: 2026-02-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0026_add_warming_lease_fields"
down_revision = "0025_add_warming_channels_and_joined_field"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("telegram_accounts", "warming_task_id"):
        op.add_column(
            "telegram_accounts",
            sa.Column("warming_task_id", sa.String(255), nullable=True),
        )

    if not _column_exists("telegram_accounts", "warming_task_started_at"):
        op.add_column(
            "telegram_accounts",
            sa.Column(
                "warming_task_started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _column_exists("telegram_accounts", "warming_task_started_at"):
        op.drop_column("telegram_accounts", "warming_task_started_at")

    if _column_exists("telegram_accounts", "warming_task_id"):
        op.drop_column("telegram_accounts", "warming_task_id")
