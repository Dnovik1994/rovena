"""Add 'error' status to AccountStatus enum and last_error column to accounts

The _resolve_api_credentials helper raises RuntimeError when API settings
are missing or invalid.  Without an 'error' status and a place to store
the message, Celery workers crash instead of gracefully marking the
account as broken.

Revision ID: 0020_add_account_error_status_and_last_error
Revises: 0019_widen_telegram_id_bigint
Create Date: 2026-02-16 00:00:00.000000
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect, text

revision = "0020_add_account_error_status_and_last_error"
down_revision = "0019_widen_telegram_id_bigint"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Extend the AccountStatus enum with 'error'
    if dialect == "postgresql":
        op.execute(text("ALTER TYPE accountstatus ADD VALUE IF NOT EXISTS 'error'"))
    # MySQL ENUMs are redefined inline — handled via column alter below if needed.

    # 2. Add the last_error column
    if not _column_exists("accounts", "last_error"):
        op.add_column("accounts", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "last_error")
    # Note: PostgreSQL does not support removing individual enum values.
    # A full enum recreation would be needed for a true downgrade.
