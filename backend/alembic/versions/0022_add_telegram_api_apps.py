"""add telegram_api_apps table

Revision ID: 0022_add_telegram_api_apps
Revises: 0021_widen_contacts_telegram_id_bigint
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_add_telegram_api_apps"
down_revision = "0021_widen_contacts_telegram_id_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_api_apps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_id", sa.Integer(), nullable=False),
        sa.Column("api_hash", sa.String(64), nullable=False),
        sa.Column("app_title", sa.String(255), nullable=True),
        sa.Column("registered_phone", sa.String(32), nullable=True),
        sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_id"),
    )


def downgrade() -> None:
    op.drop_table("telegram_api_apps")
