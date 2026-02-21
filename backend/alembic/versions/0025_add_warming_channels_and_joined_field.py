"""Add warming_channels table with seed data and warming_joined_channels field.

Creates the warming_channels table for storing public Telegram channels/groups
used during account warming. Seeds it with 30 real Ukrainian/Russian public
channels and groups.

Also adds a JSON field warming_joined_channels to telegram_accounts to track
which channels each account has already joined.

Revision ID: 0025_add_warming_channels_and_joined_field
Revises: 0024_fix_dispatch_logs_indexes_and_nullable
Create Date: 2026-02-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0025_add_warming_channels_and_joined_field"
down_revision = "0024_fix_dispatch_logs_indexes_and_nullable"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return table in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


SEED_CHANNELS = [
    # Новости
    ("ukrainenow", "channel", "uk"),
    ("unaborisfen", "channel", "uk"),
    ("truexanewsua", "channel", "uk"),
    ("ukraina_novosti", "channel", "uk"),
    ("insider_ukr", "channel", "uk"),
    # Развлечения
    ("durov", "channel", "ru"),
    ("tonkeeper", "channel", "en"),
    ("lentachold", "channel", "ru"),
    ("maborisfen", "channel", "uk"),
    ("kinomaniak", "channel", "uk"),
    # Технологии
    ("habr_com", "channel", "ru"),
    ("tproger_official", "channel", "ru"),
    ("ithumor", "channel", "ru"),
    ("dev_ua", "channel", "uk"),
    ("techno_ua", "channel", "uk"),
    # Общие / официальные
    ("telegram", "channel", "en"),
    ("teleaborisfen", "channel", "en"),
    ("TelegramTips", "channel", "en"),
    ("bbcukrainian", "channel", "uk"),
    ("ukrainska_pravda", "channel", "uk"),
    # Музыка / лайфстайл
    ("muzychka", "channel", "uk"),
    ("recepti_ua", "channel", "uk"),
    ("bookmate", "channel", "ru"),
    # Группы (публичные чаты)
    ("taborisfen_chat", "group", "uk"),
    ("ukraine_group", "group", "uk"),
    ("kyiv_chat", "group", "uk"),
    ("odessa_chat", "group", "uk"),
    ("lviv_chat", "group", "uk"),
    ("kharkiv_chat", "group", "uk"),
    ("devs_chat_ua", "group", "uk"),
]


def upgrade() -> None:
    if not _table_exists("warming_channels"):
        op.create_table(
            "warming_channels",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("username", sa.String(100), nullable=False, unique=True),
            sa.Column("channel_type", sa.String(20), nullable=False),
            sa.Column("language", sa.String(10), server_default="uk"),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

        # Seed data — INSERT IGNORE for idempotency on re-run
        conn = op.get_bind()
        for u, ct, lang in SEED_CHANNELS:
            conn.execute(sa.text(
                "INSERT IGNORE INTO warming_channels (username, channel_type, language) "
                "VALUES (:username, :channel_type, :language)"
            ), {"username": u, "channel_type": ct, "language": lang})

    # Add warming_joined_channels JSON field to telegram_accounts
    if _table_exists("telegram_accounts") and not _column_exists(
        "telegram_accounts", "warming_joined_channels"
    ):
        op.add_column(
            "telegram_accounts",
            sa.Column("warming_joined_channels", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _table_exists("warming_channels"):
        op.drop_table("warming_channels")

    if _table_exists("telegram_accounts") and _column_exists(
        "telegram_accounts", "warming_joined_channels"
    ):
        op.drop_column("telegram_accounts", "warming_joined_channels")
