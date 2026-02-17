"""Add dispatch_task_id and dispatch_started_at to invite_campaigns.

Prevents parallel dispatch tasks from running for the same campaign.

Revision ID: 0031_add_invite_campaign_dispatch_lease
Revises: 0030_deactivate_nonexistent_warming_channels
Create Date: 2026-02-17 20:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0031_add_invite_campaign_dispatch_lease"
down_revision = "0030_deactivate_nonexistent_warming_channels"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _column_exists("invite_campaigns", "dispatch_task_id"):
        op.add_column(
            "invite_campaigns",
            sa.Column("dispatch_task_id", sa.String(255), nullable=True),
        )

    if not _column_exists("invite_campaigns", "dispatch_started_at"):
        op.add_column(
            "invite_campaigns",
            sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("invite_campaigns", "dispatch_started_at"):
        op.drop_column("invite_campaigns", "dispatch_started_at")

    if _column_exists("invite_campaigns", "dispatch_task_id"):
        op.drop_column("invite_campaigns", "dispatch_task_id")
