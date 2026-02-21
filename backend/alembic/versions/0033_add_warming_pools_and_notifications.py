"""Add warming pools (bios, photos, usernames, names), admin notification
settings, and new TelegramAccount warming/trust fields.

Revision ID: 0033_add_warming_pools_and_notifications
Revises: 0032_migrate_dispatch_log_fk_to_telegram_accounts
Create Date: 2026-02-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Boolean, DateTime, Integer, String, text

revision = "0033_add_warming_pools_and_notifications"
down_revision = "0032_migrate_dispatch_log_fk_to_telegram_accounts"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers – idempotency guards via information_schema
# ---------------------------------------------------------------------------

def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table},
    ).scalar()
    return bool(row)


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(row)


def _fk_exists(table: str, constraint_name: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND CONSTRAINT_NAME = :c "
            "AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
        ),
        {"t": table, "c": constraint_name},
    ).scalar()
    return bool(row)


def _index_exists(table: str, index_name: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND INDEX_NAME = :i"
        ),
        {"t": table, "i": index_name},
    ).scalar()
    return bool(row)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    # ── 1. warming_bios ──
    if not _table_exists("warming_bios"):
        op.create_table(
            "warming_bios",
            op.Column("id", Integer, primary_key=True, autoincrement=True),
            op.Column("text", String(200), nullable=False),
            op.Column("is_active", Boolean, nullable=False, server_default="1"),
            op.Column("created_at", DateTime(timezone=True), nullable=False,
                       server_default=text("CURRENT_TIMESTAMP")),
        )

    # ── 2. warming_photos ──
    if not _table_exists("warming_photos"):
        op.create_table(
            "warming_photos",
            op.Column("id", Integer, primary_key=True, autoincrement=True),
            op.Column("filename", String(255), nullable=False),
            op.Column("file_path", String(500), nullable=False),
            op.Column("is_active", Boolean, nullable=False, server_default="1"),
            op.Column("assigned_account_id", Integer, nullable=True, unique=True),
            op.Column("created_at", DateTime(timezone=True), nullable=False,
                       server_default=text("CURRENT_TIMESTAMP")),
        )
        # FK: assigned_account_id → telegram_accounts.id
        op.create_foreign_key(
            "fk_warming_photos_assigned_account_id",
            "warming_photos",
            "telegram_accounts",
            ["assigned_account_id"],
            ["id"],
        )

    # ── 3. warming_usernames ──
    if not _table_exists("warming_usernames"):
        op.create_table(
            "warming_usernames",
            op.Column("id", Integer, primary_key=True, autoincrement=True),
            op.Column("template", String(100), nullable=False),
            op.Column("is_active", Boolean, nullable=False, server_default="1"),
            op.Column("created_at", DateTime(timezone=True), nullable=False,
                       server_default=text("CURRENT_TIMESTAMP")),
        )

    # ── 4. warming_names ──
    if not _table_exists("warming_names"):
        op.create_table(
            "warming_names",
            op.Column("id", Integer, primary_key=True, autoincrement=True),
            op.Column("first_name", String(100), nullable=False),
            op.Column("last_name", String(100), nullable=True),
            op.Column("is_active", Boolean, nullable=False, server_default="1"),
            op.Column("created_at", DateTime(timezone=True), nullable=False,
                       server_default=text("CURRENT_TIMESTAMP")),
        )

    # ── 5. admin_notification_settings ──
    if not _table_exists("admin_notification_settings"):
        op.create_table(
            "admin_notification_settings",
            op.Column("id", Integer, primary_key=True, autoincrement=True),
            op.Column("chat_id", String(50), nullable=False),
            op.Column("notify_account_banned", Boolean, nullable=False, server_default="1"),
            op.Column("notify_flood_wait", Boolean, nullable=False, server_default="1"),
            op.Column("notify_warming_failed", Boolean, nullable=False, server_default="1"),
            op.Column("notify_system_health", Boolean, nullable=False, server_default="1"),
            op.Column("notify_flood_rate_threshold", Boolean, nullable=False, server_default="1"),
            op.Column("is_active", Boolean, nullable=False, server_default="1"),
            op.Column("created_at", DateTime(timezone=True), nullable=False,
                       server_default=text("CURRENT_TIMESTAMP")),
        )

    # ── 6. New columns on telegram_accounts ──
    if not _column_exists("telegram_accounts", "is_trusted"):
        op.add_column(
            "telegram_accounts",
            op.Column("is_trusted", Boolean, nullable=False, server_default="0"),
        )

    if not _column_exists("telegram_accounts", "warming_day"):
        op.add_column(
            "telegram_accounts",
            op.Column("warming_day", Integer, nullable=False, server_default="0"),
        )

    if not _column_exists("telegram_accounts", "warming_photo_id"):
        op.add_column(
            "telegram_accounts",
            op.Column("warming_photo_id", Integer, nullable=True),
        )
        if not _fk_exists("telegram_accounts", "fk_tg_accounts_warming_photo_id"):
            op.create_foreign_key(
                "fk_tg_accounts_warming_photo_id",
                "telegram_accounts",
                "warming_photos",
                ["warming_photo_id"],
                ["id"],
            )

    if not _column_exists("telegram_accounts", "flood_wait_at"):
        op.add_column(
            "telegram_accounts",
            op.Column("flood_wait_at", DateTime(timezone=True), nullable=True),
        )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    # ── Drop columns from telegram_accounts (reverse order) ──
    if _column_exists("telegram_accounts", "flood_wait_at"):
        op.drop_column("telegram_accounts", "flood_wait_at")

    if _column_exists("telegram_accounts", "warming_photo_id"):
        if _fk_exists("telegram_accounts", "fk_tg_accounts_warming_photo_id"):
            op.drop_constraint(
                "fk_tg_accounts_warming_photo_id",
                "telegram_accounts",
                type_="foreignkey",
            )
        op.drop_column("telegram_accounts", "warming_photo_id")

    if _column_exists("telegram_accounts", "warming_day"):
        op.drop_column("telegram_accounts", "warming_day")

    if _column_exists("telegram_accounts", "is_trusted"):
        op.drop_column("telegram_accounts", "is_trusted")

    # ── Drop tables (reverse order) ──
    if _table_exists("admin_notification_settings"):
        op.drop_table("admin_notification_settings")

    if _table_exists("warming_names"):
        op.drop_table("warming_names")

    if _table_exists("warming_usernames"):
        op.drop_table("warming_usernames")

    if _table_exists("warming_photos"):
        op.drop_table("warming_photos")

    if _table_exists("warming_bios"):
        op.drop_table("warming_bios")
