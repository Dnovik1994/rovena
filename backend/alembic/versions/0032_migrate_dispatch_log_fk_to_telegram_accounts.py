"""Migrate campaign_dispatch_logs.account_id FK from accounts to telegram_accounts.

Part of Account → TelegramAccount migration (#11).

Fully idempotent: handles all four possible states:
  a) FK on accounts       → drop old, create new
  b) FK on telegram_accounts → already done, skip
  c) No FK at all         → create new
  d) Both FKs exist       → drop old, keep new

Revision ID: 0032_migrate_dispatch_log_fk_to_telegram_accounts
Revises: 0031_add_invite_campaign_dispatch_lease
Create Date: 2026-02-19 00:00:00.000000
"""

from __future__ import annotations

from typing import List

from alembic import op
from sqlalchemy import text

revision = "0032_migrate_dispatch_log_fk_to_telegram_accounts"
down_revision = "0031_add_invite_campaign_dispatch_lease"
branch_labels = None
depends_on = None

_TABLE = "campaign_dispatch_logs"
_COLUMN = "account_id"
_NEW_FK = "fk_dispatch_logs_telegram_account_id"
_OLD_FK = "fk_dispatch_logs_account_id"


def _get_fk_names_for_referred_table(referred_table: str) -> List[str]:
    """Return names of all FKs on _TABLE._COLUMN that point to *referred_table*."""
    conn = op.get_bind()
    rows = conn.execute(
        text(
            "SELECT CONSTRAINT_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :table "
            "AND COLUMN_NAME = :column "
            "AND REFERENCED_TABLE_NAME = :referred"
        ),
        {"table": _TABLE, "column": _COLUMN, "referred": referred_table},
    ).fetchall()
    return [row[0] for row in rows]


def _has_fk_to(referred_table: str) -> bool:
    return bool(_get_fk_names_for_referred_table(referred_table))


def _drop_all_fks_to(referred_table: str) -> None:
    """Drop every FK on _TABLE._COLUMN pointing to *referred_table*."""
    for name in _get_fk_names_for_referred_table(referred_table):
        op.drop_constraint(name, _TABLE, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        return

    # 1. Drop ALL old FKs pointing to accounts (regardless of name).
    _drop_all_fks_to("accounts")

    # 2. Create new FK to telegram_accounts — only if none exists yet.
    if not _has_fk_to("telegram_accounts"):
        op.create_foreign_key(
            _NEW_FK,
            _TABLE,
            "telegram_accounts",
            [_COLUMN],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        return

    # 1. Drop ALL FKs pointing to telegram_accounts.
    _drop_all_fks_to("telegram_accounts")

    # 2. Restore FK to accounts — only if none exists yet.
    if not _has_fk_to("accounts"):
        op.create_foreign_key(
            _OLD_FK,
            _TABLE,
            "accounts",
            [_COLUMN],
            ["id"],
        )
