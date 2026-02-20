"""Migrate campaign_dispatch_logs.account_id FK from accounts to telegram_accounts.

Part of Account → TelegramAccount migration (#11).

Revision ID: 0032_migrate_dispatch_log_fk_to_telegram_accounts
Revises: 0031_add_invite_campaign_dispatch_lease
Create Date: 2026-02-19 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

revision = "0032_migrate_dispatch_log_fk_to_telegram_accounts"
down_revision = "0031_add_invite_campaign_dispatch_lease"
branch_labels = None
depends_on = None

_NEW_FK = "fk_dispatch_logs_telegram_account_id"
_OLD_FK = "fk_dispatch_logs_account_id"


def _fk_exists(bind: sa.engine.Connection, constraint_name: str) -> bool:
    """Check if a foreign key constraint exists (MySQL / information_schema)."""
    result = bind.execute(
        text(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE() "
            "  AND TABLE_NAME = 'campaign_dispatch_logs' "
            "  AND CONSTRAINT_NAME = :name "
            "  AND CONSTRAINT_TYPE = 'FOREIGN KEY' "
            "LIMIT 1"
        ),
        {"name": constraint_name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    dialect = bind.dialect.name

    if dialect == "sqlite":
        # SQLite doesn't support ALTER TABLE DROP/ADD CONSTRAINT.
        # The FK is enforced at ORM level; skip DDL changes for SQLite.
        return

    # Drop the old FK pointing to accounts.id
    fks = inspector.get_foreign_keys("campaign_dispatch_logs")
    for fk in fks:
        if fk["referred_table"] == "accounts" and "account_id" in fk["constrained_columns"]:
            fk_name = fk["name"]
            if fk_name:
                op.drop_constraint(fk_name, "campaign_dispatch_logs", type_="foreignkey")
                break

    # Add new FK pointing to telegram_accounts.id (idempotent)
    if not _fk_exists(bind, _NEW_FK):
        op.create_foreign_key(
            _NEW_FK,
            "campaign_dispatch_logs",
            "telegram_accounts",
            ["account_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        return

    # Drop new FK only if it exists (idempotent)
    if _fk_exists(bind, _NEW_FK):
        op.drop_constraint(_NEW_FK, "campaign_dispatch_logs", type_="foreignkey")

    # Restore old FK only if it doesn't already exist (idempotent)
    if not _fk_exists(bind, _OLD_FK):
        op.create_foreign_key(
            _OLD_FK,
            "campaign_dispatch_logs",
            "accounts",
            ["account_id"],
            ["id"],
        )
