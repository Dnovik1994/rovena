"""add tg_users, tg_account_chats, tg_chat_members, campaign_contacts

Revision ID: 0018_add_contact_parsing_models
Revises: 0017_add_performance_indexes
Create Date: 2026-02-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0018_add_contact_parsing_models"
down_revision = "0017_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tg_users ---
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

    # --- tg_account_chats ---
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

    # --- tg_chat_members ---
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

    # --- campaign_contacts ---
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

    # --- campaigns: add new columns ---
    op.add_column("campaigns", sa.Column("max_invites_total", sa.Integer(), nullable=True))
    op.add_column("campaigns", sa.Column("invites_completed", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("campaigns", sa.Column("invite_offset", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("campaigns", sa.Column("source_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    # --- campaigns: remove new columns ---
    op.drop_column("campaigns", "source_chat_id")
    op.drop_column("campaigns", "invite_offset")
    op.drop_column("campaigns", "invites_completed")
    op.drop_column("campaigns", "max_invites_total")

    # --- drop tables in reverse order (respecting FK dependencies) ---
    op.drop_index("ix_campaign_contacts_campaign_id", table_name="campaign_contacts")
    op.drop_table("campaign_contacts")

    op.drop_index("ix_tg_chat_members_user_id", table_name="tg_chat_members")
    op.drop_index("ix_tg_chat_members_chat_id", table_name="tg_chat_members")
    op.drop_table("tg_chat_members")

    op.drop_table("tg_account_chats")

    op.drop_index("ix_tg_users_username", table_name="tg_users")
    op.drop_index("ix_tg_users_telegram_id", table_name="tg_users")
    op.drop_table("tg_users")
