"""add performance indexes

Revision ID: 0017_add_performance_indexes
Revises: 0016_add_onboarding_state
Create Date: 2025-09-21 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0017_add_performance_indexes"
down_revision = "0016_add_onboarding_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_tariff_id", "users", ["tariff_id"])
    op.create_index("ix_users_refresh_token", "users", ["refresh_token"])
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_status_proxy_id", "accounts", ["status", "proxy_id"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_index("ix_campaigns_status_project_id", "campaigns", ["status", "project_id"])
    op.create_index("ix_proxies_status", "proxies", ["status"])
    op.create_index("ix_contacts_blocked", "contacts", ["blocked"])


def downgrade() -> None:
    op.drop_index("ix_contacts_blocked", table_name="contacts")
    op.drop_index("ix_proxies_status", table_name="proxies")
    op.drop_index("ix_campaigns_status_project_id", table_name="campaigns")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_accounts_status_proxy_id", table_name="accounts")
    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_index("ix_users_refresh_token", table_name="users")
    op.drop_index("ix_users_tariff_id", table_name="users")
