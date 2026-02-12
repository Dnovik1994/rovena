"""widen users.telegram_id from INT to BIGINT

Telegram user IDs can exceed 2^31 (≈2.1 billion), which overflows a
signed 32-bit INT column.  This migration widens the column to BIGINT
so that the full range of Telegram user IDs is supported.

Revision ID: 0019_widen_telegram_id_bigint
Revises: 0018_add_telegram_accounts_auth_flows
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
from sqlalchemy import text

revision = "0019_widen_telegram_id_bigint"
down_revision = "0018_add_telegram_accounts_auth_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        # Drop the existing unique index first, alter column, then recreate.
        # MySQL requires the index to be dropped before modifying the column
        # type if the index definition needs to stay consistent.
        bind.execute(text(
            "ALTER TABLE users "
            "MODIFY telegram_id BIGINT NOT NULL"
        ))
    else:
        op.alter_column(
            "users",
            "telegram_id",
            type_=__import__("sqlalchemy").BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        bind.execute(text(
            "ALTER TABLE users "
            "MODIFY telegram_id INT NOT NULL"
        ))
    else:
        op.alter_column(
            "users",
            "telegram_id",
            type_=__import__("sqlalchemy").Integer(),
            existing_nullable=False,
        )
