"""Add code_submitted value to authflowstate enum.

Needed for unified_auth_task which polls DB for submitted codes.

Revision ID: 0027_add_code_submitted_auth_flow_state
Revises: 0026_add_warming_lease_fields
Create Date: 2026-02-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_add_code_submitted_auth_flow_state"
down_revision = "0026_add_warming_lease_fields"
branch_labels = None
depends_on = None

_NEW_ENUM = sa.Enum(
    "init", "code_sent", "wait_code", "code_submitted",
    "wait_password", "done", "expired", "failed",
    name="authflowstate",
)
_OLD_ENUM = sa.Enum(
    "init", "code_sent", "wait_code",
    "wait_password", "done", "expired", "failed",
    name="authflowstate",
)


def upgrade() -> None:
    conn = op.get_bind()
    col_type = conn.execute(sa.text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'telegram_auth_flows' "
        "AND COLUMN_NAME = 'state'"
    )).scalar()
    if col_type and "code_submitted" in col_type:
        return  # already has the new enum value
    op.alter_column(
        "telegram_auth_flows",
        "state",
        type_=_NEW_ENUM,
        existing_type=_OLD_ENUM,
        existing_nullable=False,
        existing_server_default="init",
    )


def downgrade() -> None:
    conn = op.get_bind()
    col_type = conn.execute(sa.text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'telegram_auth_flows' "
        "AND COLUMN_NAME = 'state'"
    )).scalar()
    if col_type and "code_submitted" not in col_type:
        return  # already without the value
    op.alter_column(
        "telegram_auth_flows",
        "state",
        type_=_OLD_ENUM,
        existing_type=_NEW_ENUM,
        existing_nullable=False,
        existing_server_default="init",
    )
