"""add domain models

Revision ID: 0003
Revises: 0002
Create Date: 2024-10-11 00:30:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=255), nullable=False),
        sa.Column("type", sa.Enum("group", "channel", name="sourcetype"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"])

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=255), nullable=False),
        sa.Column("type", sa.Enum("group", "channel", name="targettype"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    )
    op.create_index("ix_targets_project_id", "targets", ["project_id"])
    op.create_index("ix_targets_owner_id", "targets", ["owner_id"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
    )
    op.create_index("ix_contacts_project_id", "contacts", ["project_id"])
    op.create_index("ix_contacts_owner_id", "contacts", ["owner_id"])
    op.create_index("ix_contacts_source_id", "contacts", ["source_id"])
    op.create_index("ix_contacts_telegram_id", "contacts", ["telegram_id"], unique=True)

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "paused", "completed", name="campaignstatus"),
            nullable=False,
        ),
        sa.Column("max_invites_per_hour", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_invites_per_day", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"]),
    )
    op.create_index("ix_campaigns_project_id", "campaigns", ["project_id"])
    op.create_index("ix_campaigns_owner_id", "campaigns", ["owner_id"])
    op.create_index("ix_campaigns_source_id", "campaigns", ["source_id"])
    op.create_index("ix_campaigns_target_id", "campaigns", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_campaigns_target_id", table_name="campaigns")
    op.drop_index("ix_campaigns_source_id", table_name="campaigns")
    op.drop_index("ix_campaigns_owner_id", table_name="campaigns")
    op.drop_index("ix_campaigns_project_id", table_name="campaigns")
    op.drop_table("campaigns")

    op.drop_index("ix_contacts_telegram_id", table_name="contacts")
    op.drop_index("ix_contacts_source_id", table_name="contacts")
    op.drop_index("ix_contacts_owner_id", table_name="contacts")
    op.drop_index("ix_contacts_project_id", table_name="contacts")
    op.drop_table("contacts")

    op.drop_index("ix_targets_owner_id", table_name="targets")
    op.drop_index("ix_targets_project_id", table_name="targets")
    op.drop_table("targets")

    op.drop_index("ix_sources_owner_id", table_name="sources")
    op.drop_index("ix_sources_project_id", table_name="sources")
    op.drop_table("sources")

    # MySQL auto-drops ENUM with column, no separate DROP TYPE needed
    pass
