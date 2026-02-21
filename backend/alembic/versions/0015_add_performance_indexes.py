"""add performance indexes

Revision ID: 0015_add_performance_indexes
Revises: 0014_add_refresh_token
Create Date: 2025-09-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0015_add_performance_indexes"
down_revision = "0014_add_refresh_token"
branch_labels = None
depends_on = None


def _create_index_if_missing(index_name: str, table_name: str, columns: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        exists = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.statistics
                WHERE index_name = :index_name
                  AND table_name = :table_name
                  AND table_schema = DATABASE()
                LIMIT 1
                """
            ),
            {"index_name": index_name, "table_name": table_name},
        ).scalar()
        if exists:
            return
        op.execute(f"CREATE INDEX {index_name} ON {table_name} ({columns})")
        return

    op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})")


def upgrade() -> None:
    _create_index_if_missing("ix_users_tariff_id", "users", "tariff_id")
    _create_index_if_missing("ix_accounts_status", "accounts", "status")
    _create_index_if_missing("ix_campaigns_status", "campaigns", "status")
    _create_index_if_missing("ix_proxies_status", "proxies", "status")
    _create_index_if_missing("ix_contacts_blocked", "contacts", "blocked")


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND INDEX_NAME = :idx "
            "AND TABLE_NAME = :tbl"
        ),
        {"idx": index_name, "tbl": table_name},
    ).scalar()
    if exists:
        op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    _drop_index_if_exists("ix_contacts_blocked", "contacts")
    _drop_index_if_exists("ix_proxies_status", "proxies")
    _drop_index_if_exists("ix_campaigns_status", "campaigns")
    _drop_index_if_exists("ix_accounts_status", "accounts")
    _drop_index_if_exists("ix_users_tariff_id", "users")
