"""Add missing indexes and fix nullable on campaign_dispatch_logs.

- Add indexes on account_id and contact_id (declared in model with index=True
  but never created in migrations 0009/0010).
- Fix timestamp column: model declares NOT NULL but migration 0010 created it
  as nullable=True.  Backfill any NULLs with created_at before altering.

Revision ID: 0024_fix_dispatch_logs_indexes_and_nullable
Revises: 0023_unique_api_app_proxy
Create Date: 2026-02-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect, text

revision = "0024_fix_dispatch_logs_indexes_and_nullable"
down_revision = "0023_unique_api_app_proxy"
branch_labels = None
depends_on = None

_TABLE = "campaign_dispatch_logs"


def _index_exists(inspector, index_name: str) -> bool:
    for idx in inspector.get_indexes(_TABLE):
        if idx["name"] == index_name:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    # --- indexes ---
    if not _index_exists(inspector, "ix_campaign_dispatch_logs_account_id"):
        op.create_index(
            "ix_campaign_dispatch_logs_account_id",
            _TABLE,
            ["account_id"],
        )

    if not _index_exists(inspector, "ix_campaign_dispatch_logs_contact_id"):
        op.create_index(
            "ix_campaign_dispatch_logs_contact_id",
            _TABLE,
            ["contact_id"],
        )

    # --- fix timestamp nullable ---
    # Backfill NULLs with created_at (both columns always present since 0009)
    batch_size = 5000
    while True:
        result = bind.execute(
            text(
                f"UPDATE {_TABLE} SET timestamp = created_at "
                f"WHERE timestamp IS NULL LIMIT :batch"
            ),
            {"batch": batch_size},
        )
        if result.rowcount == 0:
            break
    op.alter_column(
        _TABLE,
        "timestamp",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        _TABLE,
        "timestamp",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.drop_index("ix_campaign_dispatch_logs_contact_id", table_name=_TABLE)
    op.drop_index("ix_campaign_dispatch_logs_account_id", table_name=_TABLE)
