"""add telegram_accounts and telegram_auth_flows tables

Revision ID: 0018_add_telegram_accounts_auth_flows
Revises: 0017_add_performance_indexes
Create Date: 2026-02-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_add_telegram_accounts_auth_flows"
down_revision = "0017_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("phone_e164", sa.String(32), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new", "code_sent", "password_required", "verified",
                "disconnected", "error", "banned", "warming", "active", "cooldown",
                name="telegramaccountstatus",
            ),
            nullable=False,
            server_default="new",
        ),
        sa.Column("session_encrypted", sa.Text(), nullable=True),
        sa.Column("device_config", sa.JSON(), nullable=True),
        sa.Column("proxy_id", sa.Integer(), sa.ForeignKey("proxies.id"), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("warming_actions_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("target_warming_actions", sa.Integer(), server_default="10", nullable=False),
        sa.Column("warming_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_device_regenerated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tg_accounts_owner_phone", "telegram_accounts", ["owner_user_id", "phone_e164"], unique=True)
    op.create_index("ix_tg_accounts_owner_id", "telegram_accounts", ["owner_user_id"])
    op.create_index("ix_tg_accounts_status", "telegram_accounts", ["status"])

    op.create_table(
        "telegram_auth_flows",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("telegram_accounts.id"), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "init", "code_sent", "wait_code", "wait_password",
                "done", "expired", "failed",
                name="authflowstate",
            ),
            nullable=False,
            server_default="init",
        ),
        sa.Column("phone_e164", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_flows_account_id", "telegram_auth_flows", ["account_id"])
    op.create_index("ix_auth_flows_expires_at", "telegram_auth_flows", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_flows_expires_at", table_name="telegram_auth_flows")
    op.drop_index("ix_auth_flows_account_id", table_name="telegram_auth_flows")
    op.drop_table("telegram_auth_flows")

    op.drop_index("ix_tg_accounts_status", table_name="telegram_accounts")
    op.drop_index("ix_tg_accounts_owner_id", table_name="telegram_accounts")
    op.drop_index("ix_tg_accounts_owner_phone", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
