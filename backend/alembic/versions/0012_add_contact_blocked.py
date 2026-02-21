"""add contact blocked fields

Revision ID: 0012
Revises: 0011
Create Date: 2024-10-12 04:10:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        contact_columns = set()
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}

    if "blocked" not in contact_columns:
        op.add_column(
            "contacts",
            sa.Column("blocked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.alter_column("contacts", "blocked", server_default=None)

    if "blocked_reason" not in contact_columns:
        op.add_column("contacts", sa.Column("blocked_reason", sa.String(255), nullable=True))

    if "is_blocked" in contact_columns:
        conn = op.get_bind()
        batch_size = 5000
        while True:
            result = conn.execute(sa.text(
                "UPDATE contacts SET blocked = is_blocked "
                "WHERE is_blocked = 1 AND blocked != is_blocked LIMIT :batch"
            ), {"batch": batch_size})
            if result.rowcount == 0:
                break
        op.drop_column("contacts", "is_blocked")


def downgrade() -> None:
    if context.is_offline_mode():
        contact_columns = {"blocked", "blocked_reason"}
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}

    if "is_blocked" not in contact_columns:
        op.add_column(
            "contacts",
            sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.alter_column("contacts", "is_blocked", server_default=None)

    if "blocked" in contact_columns:
        conn = op.get_bind()
        batch_size = 5000
        while True:
            result = conn.execute(sa.text(
                "UPDATE contacts SET is_blocked = blocked "
                "WHERE blocked = 1 AND is_blocked != blocked LIMIT :batch"
            ), {"batch": batch_size})
            if result.rowcount == 0:
                break
        op.drop_column("contacts", "blocked")

    if "blocked_reason" in contact_columns:
        op.drop_column("contacts", "blocked_reason")
