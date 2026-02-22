"""Add index on mechanic_profiles.stripe_account_id

H-023: stripe_account_id was queried in webhook lookups without an index,
causing full table scans.

Revision ID: 031
Revises: 030
Create Date: 2026-02-22
"""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_mechanic_profiles_stripe_account_id",
        "mechanic_profiles",
        ["stripe_account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mechanic_profiles_stripe_account_id", table_name="mechanic_profiles")
