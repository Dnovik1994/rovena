"""add dispatch error details

Revision ID: 0010
Revises: 0009
Create Date: 2024-10-12 02:40:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        contact_columns = set()
        log_columns = set()
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
        log_columns = {column["name"] for column in inspector.get_columns("campaign_dispatch_logs")}

    if "is_blocked" not in contact_columns:
        op.add_column(
            "contacts",
            sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.alter_column("contacts", "is_blocked", server_default=None)

    if "error_type" not in log_columns:
        op.add_column(
            "campaign_dispatch_logs",
            sa.Column(
                "error_type",
                sa.Enum(
                    "FloodWait",
                    "UserPrivacyRestricted",
                    "PeerIdInvalid",
                    "UserBlocked",
                    "Other",
                    name="dispatcherrortype",
                ),
                nullable=False,
                server_default="Other",
            ),
        )
        op.alter_column("campaign_dispatch_logs", "error_type", server_default=None)

    if "error_message" not in log_columns:
        op.add_column(
            "campaign_dispatch_logs",
            sa.Column("error_message", sa.String(length=255), nullable=True),
        )

    if "timestamp" not in log_columns:
        op.add_column(
            "campaign_dispatch_logs",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if context.is_offline_mode():
        log_columns = {"timestamp", "error_message", "error_type"}
        contact_columns = {"is_blocked"}
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        log_columns = {column["name"] for column in inspector.get_columns("campaign_dispatch_logs")}
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}

    if "timestamp" in log_columns:
        op.drop_column("campaign_dispatch_logs", "timestamp")
    if "error_message" in log_columns:
        op.drop_column("campaign_dispatch_logs", "error_message")
    if "error_type" in log_columns:
        op.drop_column("campaign_dispatch_logs", "error_type")
        # MySQL auto-drops ENUM with column, no separate DROP TYPE needed

    if "is_blocked" in contact_columns:
        op.drop_column("contacts", "is_blocked")
