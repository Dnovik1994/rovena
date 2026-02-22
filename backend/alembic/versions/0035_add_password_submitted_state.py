"""Add password_submitted to auth_flow_state enum.

Revision ID: 0035_add_password_submitted_state
Revises: 0034_add_notify_warming_completed
Create Date: 2026-02-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0035_add_password_submitted_state"
down_revision = "0034_add_notify_warming_completed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE telegram_auth_flows MODIFY COLUMN state ENUM("
               "'init','code_sent','wait_code','code_submitted',"
               "'wait_password','password_submitted',"
               "'done','expired','failed'"
               ") NOT NULL DEFAULT 'init'")


def downgrade() -> None:
    # Move any password_submitted rows back to wait_password before shrinking enum
    op.execute("UPDATE telegram_auth_flows SET state='wait_password' "
               "WHERE state='password_submitted'")
    op.execute("ALTER TABLE telegram_auth_flows MODIFY COLUMN state ENUM("
               "'init','code_sent','wait_code','code_submitted',"
               "'wait_password',"
               "'done','expired','failed'"
               ") NOT NULL DEFAULT 'init'")
