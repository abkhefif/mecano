"""Change Booking FK ondelete from CASCADE to RESTRICT

ARCH-007: Prevent accidental cascade deletion of financial records.
If a user row is deleted via raw SQL, all their bookings (including
payment data, reviews, disputes) would be permanently lost. The GDPR
delete flow anonymizes users instead of deleting them, so CASCADE is
not needed and RESTRICT is safer.

Revision ID: 026
Revises: 025
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old CASCADE FKs and recreate with RESTRICT
    # buyer_id -> users.id
    try:
        op.drop_constraint("bookings_buyer_id_fkey", "bookings", type_="foreignkey")
    except Exception:
        pass  # Constraint name may differ
    op.create_foreign_key(
        "bookings_buyer_id_fkey",
        "bookings",
        "users",
        ["buyer_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # mechanic_id -> mechanic_profiles.id
    try:
        op.drop_constraint("bookings_mechanic_id_fkey", "bookings", type_="foreignkey")
    except Exception:
        pass
    op.create_foreign_key(
        "bookings_mechanic_id_fkey",
        "bookings",
        "mechanic_profiles",
        ["mechanic_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Revert to CASCADE
    try:
        op.drop_constraint("bookings_buyer_id_fkey", "bookings", type_="foreignkey")
    except Exception:
        pass
    op.create_foreign_key(
        "bookings_buyer_id_fkey",
        "bookings",
        "users",
        ["buyer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    try:
        op.drop_constraint("bookings_mechanic_id_fkey", "bookings", type_="foreignkey")
    except Exception:
        pass
    op.create_foreign_key(
        "bookings_mechanic_id_fkey",
        "bookings",
        "mechanic_profiles",
        ["mechanic_id"],
        ["id"],
        ondelete="CASCADE",
    )
