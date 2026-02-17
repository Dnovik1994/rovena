"""add accounts and proxies

Revision ID: 0004
Revises: 0003
Create Date: 2024-10-11 00:50:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proxies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=True),
        sa.Column(
            "type",
            sa.Enum("http", "socks5", "residential", name="proxytype"),
            nullable=False,
        ),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "error", name="proxystatus"),
            nullable=False,
        ),
        sa.Column("last_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("new", "warming", "active", "cooldown", "blocked", name="accountstatus"),
            nullable=False,
        ),
        sa.Column("proxy_id", sa.Integer(), nullable=True),
        sa.Column("device_config", sa.JSON(), nullable=True),
        sa.Column("warming_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["proxy_id"], ["proxies.id"]),
    )

    op.create_index("ix_accounts_user_id", "accounts", ["user_id"])
    op.create_index("ix_accounts_owner_id", "accounts", ["owner_id"])
    op.create_index("ix_accounts_proxy_id", "accounts", ["proxy_id"])
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_telegram_id", "accounts", ["telegram_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_accounts_telegram_id", table_name="accounts")
    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_index("ix_accounts_proxy_id", table_name="accounts")
    op.drop_index("ix_accounts_owner_id", table_name="accounts")
    op.drop_index("ix_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")

    op.drop_table("proxies")

    # MySQL auto-drops ENUM with column, no separate DROP TYPE needed
    pass
