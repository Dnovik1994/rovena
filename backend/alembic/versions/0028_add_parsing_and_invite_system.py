"""Add contact-parsing tables and invite-campaign system.

Creates tables: tg_users, tg_account_chats, tg_chat_members,
campaign_contacts, invite_campaigns, invite_tasks.
Adds invite-related columns to existing campaigns table.

Revision ID: 0028_add_parsing_and_invite_system
Revises: 0027_add_code_submitted_auth_flow_state
Create Date: 2026-02-17 05:45:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0028_add_parsing_and_invite_system"
down_revision = "0027_add_code_submitted_auth_flow_state"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # ── tg_users ──────────────────────────────────────────────────────
    if not _table_exists("tg_users"):
        op.create_table(
            "tg_users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("access_hash", sa.BigInteger(), nullable=True),
            sa.Column("username", sa.String(100), nullable=True),
            sa.Column("first_name", sa.String(255), nullable=True),
            sa.Column("last_name", sa.String(255), nullable=True),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_online_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("telegram_id"),
        )
        op.create_index("ix_tg_users_telegram_id", "tg_users", ["telegram_id"])
        op.create_index("ix_tg_users_username", "tg_users", ["username"])

    # ── tg_account_chats ──────────────────────────────────────────────
    if not _table_exists("tg_account_chats"):
        op.create_table(
            "tg_account_chats",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("title", sa.String(255), nullable=True),
            sa.Column("username", sa.String(100), nullable=True),
            sa.Column("chat_type", sa.String(20), nullable=False),
            sa.Column("members_count", sa.Integer(), nullable=True),
            sa.Column("is_creator", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_parsed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["account_id"], ["telegram_accounts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("account_id", "chat_id", name="uq_account_chat"),
        )

    # ── tg_chat_members ───────────────────────────────────────────────
    if not _table_exists("tg_chat_members"):
        op.create_table(
            "tg_chat_members",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column(
                "role",
                sa.Enum("owner", "admin", "member", "restricted", "banned", name="chatmemberrole"),
                nullable=False,
                server_default="member",
            ),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["tg_users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
        )
        op.create_index("ix_tg_chat_members_chat_id", "tg_chat_members", ["chat_id"])
        op.create_index("ix_tg_chat_members_user_id", "tg_chat_members", ["user_id"])

    # ── campaign_contacts ─────────────────────────────────────────────
    if not _table_exists("campaign_contacts"):
        op.create_table(
            "campaign_contacts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("tg_user_id", sa.Integer(), nullable=False),
            sa.Column(
                "invite_status",
                sa.Enum("pending", "invited", "failed", "already_member", "left", "flood_wait", name="invitestatus"),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("invited_by_account_id", sa.Integer(), nullable=True),
            sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.String(500), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tg_user_id"], ["tg_users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invited_by_account_id"], ["telegram_accounts.id"]),
            sa.UniqueConstraint("campaign_id", "tg_user_id", name="uq_campaign_contact"),
        )
        op.create_index("ix_campaign_contacts_campaign_id", "campaign_contacts", ["campaign_id"])

    # ── campaigns: add invite-related columns ─────────────────────────
    if _table_exists("campaigns"):
        if not _column_exists("campaigns", "max_invites_total"):
            op.add_column("campaigns", sa.Column("max_invites_total", sa.Integer(), nullable=True))
        if not _column_exists("campaigns", "invites_completed"):
            op.add_column(
                "campaigns",
                sa.Column("invites_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
        if not _column_exists("campaigns", "invite_offset"):
            op.add_column(
                "campaigns",
                sa.Column("invite_offset", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
        if not _column_exists("campaigns", "source_chat_id"):
            op.add_column("campaigns", sa.Column("source_chat_id", sa.BigInteger(), nullable=True))

    # ── invite_campaigns ──────────────────────────────────────────────
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
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        )
        op.create_index("ix_invite_campaigns_owner_id", "invite_campaigns", ["owner_id"])

    # ── invite_tasks ──────────────────────────────────────────────────
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
    if _table_exists("invite_tasks"):
        op.drop_table("invite_tasks")
    if _table_exists("invite_campaigns"):
        op.drop_table("invite_campaigns")

    if _table_exists("campaigns"):
        for col in ("source_chat_id", "invite_offset", "invites_completed", "max_invites_total"):
            if _column_exists("campaigns", col):
                op.drop_column("campaigns", col)

    if _table_exists("campaign_contacts"):
        op.drop_table("campaign_contacts")
    if _table_exists("tg_chat_members"):
        op.drop_table("tg_chat_members")
    if _table_exists("tg_account_chats"):
        op.drop_table("tg_account_chats")
    if _table_exists("tg_users"):
        op.drop_table("tg_users")
