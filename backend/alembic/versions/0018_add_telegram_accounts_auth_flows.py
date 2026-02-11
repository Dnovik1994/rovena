"""add telegram_accounts and telegram_auth_flows tables

Revision ID: 0018_add_telegram_accounts_auth_flows
Revises: 0017b_widen_alembic_version_num
Create Date: 2026-02-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0018_add_telegram_accounts_auth_flows"
down_revision = "0017b_widen_alembic_version_num"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    """Check whether *name* already exists in the current database."""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return name in inspector.get_table_names()


def _index_exists(name: str, table: str) -> bool:
    """Check whether index *name* already exists on *table*."""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    if not _table_exists("telegram_accounts"):
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

    if not _index_exists("ix_tg_accounts_owner_phone", "telegram_accounts"):
        op.create_index("ix_tg_accounts_owner_phone", "telegram_accounts", ["owner_user_id", "phone_e164"], unique=True)
    if not _index_exists("ix_tg_accounts_owner_id", "telegram_accounts"):
        op.create_index("ix_tg_accounts_owner_id", "telegram_accounts", ["owner_user_id"])
    if not _index_exists("ix_tg_accounts_status", "telegram_accounts"):
        op.create_index("ix_tg_accounts_status", "telegram_accounts", ["status"])

    if not _table_exists("telegram_auth_flows"):
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

    if _table_exists("telegram_auth_flows"):
        if not _index_exists("ix_auth_flows_account_id", "telegram_auth_flows"):
            op.create_index("ix_auth_flows_account_id", "telegram_auth_flows", ["account_id"])
        if not _index_exists("ix_auth_flows_expires_at", "telegram_auth_flows"):
            op.create_index("ix_auth_flows_expires_at", "telegram_auth_flows", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_flows_expires_at", table_name="telegram_auth_flows")
    op.drop_index("ix_auth_flows_account_id", table_name="telegram_auth_flows")
    op.drop_table("telegram_auth_flows")

    op.drop_index("ix_tg_accounts_status", table_name="telegram_accounts")
    op.drop_index("ix_tg_accounts_owner_id", table_name="telegram_accounts")
    op.drop_index("ix_tg_accounts_owner_phone", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
