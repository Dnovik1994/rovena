"""Add verify lease/lock fields to telegram_accounts

Revision ID: 0020_add_verify_lease_fields
Revises: 0020_add_account_error_status_and_last_error
Create Date: 2026-02-11 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0020_add_verify_lease_fields"
down_revision = "0020_add_account_error_status_and_last_error"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("telegram_accounts", "verifying"):
        op.add_column(
            "telegram_accounts",
            sa.Column("verifying", sa.Boolean(), nullable=False, server_default="0"),
        )
    if not _column_exists("telegram_accounts", "verifying_started_at"):
        op.add_column(
            "telegram_accounts",
            sa.Column("verifying_started_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists("telegram_accounts", "verifying_task_id"):
        op.add_column(
            "telegram_accounts",
            sa.Column("verifying_task_id", sa.String(255), nullable=True),
        )
    if not _column_exists("telegram_accounts", "verify_status"):
        op.add_column(
            "telegram_accounts",
            sa.Column("verify_status", sa.String(32), nullable=True),
        )
    if not _column_exists("telegram_accounts", "verify_reason"):
        op.add_column(
            "telegram_accounts",
            sa.Column("verify_reason", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("telegram_accounts", "verify_reason")
    op.drop_column("telegram_accounts", "verify_status")
    op.drop_column("telegram_accounts", "verifying_task_id")
    op.drop_column("telegram_accounts", "verifying_started_at")
    op.drop_column("telegram_accounts", "verifying")
