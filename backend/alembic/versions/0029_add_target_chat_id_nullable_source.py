"""Add target_chat_id to invite_campaigns, make source_chat_id and target_link nullable.

Revision ID: 0029_add_target_chat_id_nullable_source
Revises: 0028_add_parsing_and_invite_system
Create Date: 2026-02-17 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0029_add_target_chat_id_nullable_source"
down_revision = "0028_add_parsing_and_invite_system"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # Add target_chat_id column
    if not _column_exists("invite_campaigns", "target_chat_id"):
        op.add_column(
            "invite_campaigns",
            sa.Column("target_chat_id", sa.BigInteger(), nullable=True),
        )

    # Make source_chat_id nullable (skip if already nullable)
    conn = op.get_bind()
    is_nullable = conn.execute(sa.text(
        "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'invite_campaigns' "
        "AND COLUMN_NAME = 'source_chat_id'"
    )).scalar()
    if is_nullable == "NO":
        op.alter_column(
            "invite_campaigns",
            "source_chat_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )

    # Make target_link nullable (skip if already nullable)
    is_nullable = conn.execute(sa.text(
        "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'invite_campaigns' "
        "AND COLUMN_NAME = 'target_link'"
    )).scalar()
    if is_nullable == "NO":
        op.alter_column(
            "invite_campaigns",
            "target_link",
            existing_type=sa.String(500),
            nullable=True,
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Make target_link non-nullable again (skip if already non-nullable)
    is_nullable = conn.execute(sa.text(
        "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'invite_campaigns' "
        "AND COLUMN_NAME = 'target_link'"
    )).scalar()
    if is_nullable == "YES":
        op.alter_column(
            "invite_campaigns",
            "target_link",
            existing_type=sa.String(500),
            nullable=False,
        )

    # Make source_chat_id non-nullable again (skip if already non-nullable)
    is_nullable = conn.execute(sa.text(
        "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'invite_campaigns' "
        "AND COLUMN_NAME = 'source_chat_id'"
    )).scalar()
    if is_nullable == "YES":
        op.alter_column(
            "invite_campaigns",
            "source_chat_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )

    # Drop target_chat_id column
    if _column_exists("invite_campaigns", "target_chat_id"):
        op.drop_column("invite_campaigns", "target_chat_id")
