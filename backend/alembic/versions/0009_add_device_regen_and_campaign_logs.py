"""add device regeneration and campaign logs

Revision ID: 0009
Revises: 0008
Create Date: 2024-10-12 01:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "last_device_regenerated_at" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column("last_device_regenerated_at", sa.DateTime(timezone=True), nullable=True),
        )

    campaign_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "progress" not in campaign_columns:
        op.add_column(
            "campaigns",
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        )
        op.alter_column("campaigns", "progress", server_default=None)

    tables = set(inspector.get_table_names())
    if "campaign_dispatch_logs" not in tables:
        op.create_table(
            "campaign_dispatch_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("contact_id", sa.Integer(), nullable=True),
            sa.Column("error", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        )
        op.create_index(
            "ix_campaign_dispatch_logs_campaign_id",
            "campaign_dispatch_logs",
            ["campaign_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = set(inspector.get_table_names())
    if "campaign_dispatch_logs" in tables:
        op.drop_index("ix_campaign_dispatch_logs_campaign_id", table_name="campaign_dispatch_logs")
        op.drop_table("campaign_dispatch_logs")

    campaign_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "progress" in campaign_columns:
        op.drop_column("campaigns", "progress")

    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "last_device_regenerated_at" in account_columns:
        op.drop_column("accounts", "last_device_regenerated_at")
