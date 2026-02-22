"""F-01: Add check constraint enforcing mechanic_payout = total_price - commission_amount

This prevents inconsistent financial data from manual admin edits or future migrations.

Revision ID: 034
Revises: 033
Create Date: 2026-02-22
"""

from alembic import op

revision = "034"
down_revision = "033"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_bookings_payout_integrity",
        "bookings",
        "mechanic_payout = total_price - commission_amount",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bookings_payout_integrity", "bookings", type_="check")
