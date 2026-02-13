"""Add blacklisted_tokens table, cancelled_by CHECK constraint, and diploma CASCADE FK

Revision ID: 014
Revises: 013
Create Date: 2026-02-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # C-03: blacklisted_tokens table
    op.create_table(
        "blacklisted_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("jti", sa.String(36), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # M-07: cancelled_by CHECK constraint
    op.create_check_constraint(
        "ck_booking_cancelled_by_valid",
        "bookings",
        "cancelled_by IN ('buyer', 'mechanic') OR cancelled_by IS NULL",
    )

    # L-03: ondelete CASCADE on Diploma FK
    # Drop old FK and recreate with CASCADE
    op.drop_constraint("diplomas_mechanic_id_fkey", "diplomas", type_="foreignkey")
    op.create_foreign_key(
        "diplomas_mechanic_id_fkey",
        "diplomas",
        "mechanic_profiles",
        ["mechanic_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Reverse L-03
    op.drop_constraint("diplomas_mechanic_id_fkey", "diplomas", type_="foreignkey")
    op.create_foreign_key(
        "diplomas_mechanic_id_fkey",
        "diplomas",
        "mechanic_profiles",
        ["mechanic_id"],
        ["id"],
    )

    # Reverse M-07
    op.drop_constraint("ck_booking_cancelled_by_valid", "bookings", type_="check")

    # Reverse C-03
    op.drop_table("blacklisted_tokens")
