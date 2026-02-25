"""Fix existing users with is_active=false — set all to true.

No admin interface exists yet, so no user was intentionally deactivated.
The is_active column may have defaulted to false for users created before
the server_default was applied.

Revision ID: 039
Revises: 038
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET is_active = true WHERE is_active = false")


def downgrade() -> None:
    pass  # Cannot reverse — we don't know which users were originally false
