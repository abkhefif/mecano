"""Add stripe_fee column to bookings

Revision ID: 036
Revises: 035
"""

from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("stripe_fee", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )


def downgrade() -> None:
    op.drop_column("bookings", "stripe_fee")
