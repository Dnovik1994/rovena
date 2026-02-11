"""Widen alembic_version.version_num to VARCHAR(128).

Default Alembic creates version_num as VARCHAR(32) which is too short
for revision IDs like '0018_add_telegram_accounts_auth_flows' (41 chars).

Revision ID: 0019_widen_alembic_ver
Revises: 0018_add_telegram_accounts_auth_flows
Create Date: 2026-02-11 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0019_widen_alembic_ver"
down_revision = "0018_add_telegram_accounts_auth_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        # Idempotent: MySQL allows re-applying the same ALTER.
        op.execute(
            "ALTER TABLE alembic_version MODIFY version_num VARCHAR(128) NOT NULL"
        )


def downgrade() -> None:
    # Intentionally left empty — shrinking the column could lose data.
    pass
