"""Add invite_campaigns and invite_tasks tables.

New invite system — separate from legacy campaigns.

Revision ID: 0028_add_invite_campaigns_system
Revises: 0027_add_code_submitted_auth_flow_state
Create Date: 2026-02-17 05:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_add_invite_campaigns_system"
down_revision = "0027_add_code_submitted_auth_flow_state"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :t"),
        {"t": table_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    if not _table_exists("invite_campaigns"):
        op.create_table(
            "invite_campaigns",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "status",
                sa.Enum("draft", "active", "paused", "completed", "error", name="invitecampaignstatus"),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
            sa.Column("source_title", sa.String(255), nullable=True),
            sa.Column("target_link", sa.String(500), nullable=False),
            sa.Column("target_title", sa.String(255), nullable=True),
            sa.Column("max_invites_total", sa.Integer(), nullable=False),
            sa.Column("invites_per_hour_per_account", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("invites_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invites_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_invite_campaigns_owner_id", "invite_campaigns", ["owner_id"])

    if not _table_exists("invite_tasks"):
        op.create_table(
            "invite_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("tg_user_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("pending", "in_progress", "success", "failed", "skipped", name="invitetaskstatus"),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("error_message", sa.String(500), nullable=True),
            sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["campaign_id"], ["invite_campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tg_user_id"], ["tg_users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["account_id"], ["telegram_accounts.id"]),
            sa.UniqueConstraint("campaign_id", "tg_user_id", name="uq_invite_task"),
        )
        op.create_index("ix_invite_tasks_campaign_id", "invite_tasks", ["campaign_id"])


def downgrade() -> None:
    op.drop_table("invite_tasks")
    op.drop_table("invite_campaigns")
