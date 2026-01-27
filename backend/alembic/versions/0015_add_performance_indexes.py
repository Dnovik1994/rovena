"""add performance indexes

Revision ID: 0015_add_performance_indexes
Revises: 0014_add_refresh_token
Create Date: 2025-09-20 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0015_add_performance_indexes"
down_revision = "0014_add_refresh_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_tariff_id", "users", ["tariff_id"])
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_index("ix_proxies_status", "proxies", ["status"])
    op.create_index("ix_contacts_blocked", "contacts", ["blocked"])


def downgrade() -> None:
    op.drop_index("ix_contacts_blocked", table_name="contacts")
    op.drop_index("ix_proxies_status", table_name="proxies")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_index("ix_users_tariff_id", table_name="users")
