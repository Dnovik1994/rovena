"""Add notify_warming_completed column to admin_notification_settings.

Revision ID: 0034_add_notify_warming_completed
Revises: 0033_add_warming_pools_and_notifications
Create Date: 2026-02-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Boolean, text

revision = "0034_add_notify_warming_completed"
down_revision = "0033_add_warming_pools_and_notifications"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    if not _column_exists("admin_notification_settings", "notify_warming_completed"):
        op.add_column(
            "admin_notification_settings",
            op.Column("notify_warming_completed", Boolean, nullable=False, server_default="1"),
        )


def downgrade() -> None:
    if _column_exists("admin_notification_settings", "notify_warming_completed"):
        op.drop_column("admin_notification_settings", "notify_warming_completed")
