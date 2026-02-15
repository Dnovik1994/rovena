"""Add telegram_api_apps table

Revision ID: 0022_add_telegram_api_apps
Revises: 0021_widen_contacts_telegram_id_bigint
Create Date: 2026-02-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0022_add_telegram_api_apps"
down_revision = "0021_widen_contacts_telegram_id_bigint"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("telegram_api_apps"):
        return

    op.create_table(
        "telegram_api_apps",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("api_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("api_hash", sa.String(64), nullable=False),
        sa.Column("app_title", sa.String(255), nullable=True),
        sa.Column("registered_phone", sa.String(32), nullable=True),
        sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("telegram_api_apps")
