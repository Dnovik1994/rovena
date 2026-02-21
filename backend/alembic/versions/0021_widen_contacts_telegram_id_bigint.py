"""widen contacts.telegram_id from INT to BIGINT

Telegram user IDs can exceed 2^31 (~2.1 billion), which overflows a
signed 32-bit INT column.  Migration 0019 already widened users.telegram_id;
this migration applies the same fix to contacts.telegram_id.

Revision ID: 0021_widen_contacts_telegram_id_bigint
Revises: 0020_add_verify_lease_fields
Create Date: 2026-02-12 00:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect, text

revision = "0021_widen_contacts_telegram_id_bigint"
down_revision = "0020_add_verify_lease_fields"
branch_labels = None
depends_on = None


def _column_is_bigint(table: str, column: str) -> bool:
    """Return True if the column is already BIGINT (idempotency guard)."""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    for col in inspector.get_columns(table):
        if col["name"] == column:
            type_name = str(col["type"]).upper()
            return "BIGINT" in type_name
    return False


def upgrade() -> None:
    if _column_is_bigint("contacts", "telegram_id"):
        return  # already BIGINT – nothing to do

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        bind.execute(text(
            "ALTER TABLE contacts "
            "MODIFY telegram_id BIGINT NOT NULL"
        ))
    else:
        op.alter_column(
            "contacts",
            "telegram_id",
            type_=__import__("sqlalchemy").BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # WARNING: BIGINT→INT downgrade may cause data truncation if any
    # contacts.telegram_id value exceeds 2^31-1 (2147483647).
    bind = op.get_bind()
    max_val = bind.execute(text(
        "SELECT MAX(telegram_id) FROM contacts"
    )).scalar()
    if max_val is not None and max_val > 2147483647:
        raise RuntimeError(
            f"Cannot downgrade contacts.telegram_id to INT: max value {max_val} "
            f"exceeds 2^31-1 (2147483647)"
        )
    if bind.dialect.name == "mysql":
        bind.execute(text(
            "ALTER TABLE contacts "
            "MODIFY telegram_id INT NOT NULL"
        ))
    else:
        op.alter_column(
            "contacts",
            "telegram_id",
            type_=__import__("sqlalchemy").Integer(),
            existing_nullable=False,
        )
