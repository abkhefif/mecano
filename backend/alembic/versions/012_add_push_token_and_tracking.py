"""Add expo_push_token to users, mechanic tracking fields to bookings

Revision ID: 012
Revises: 011
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("expo_push_token", sa.String(100), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("mechanic_lat", sa.Numeric(9, 6), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("mechanic_lng", sa.Numeric(9, 6), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("mechanic_location_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "mechanic_location_updated_at")
    op.drop_column("bookings", "mechanic_lng")
    op.drop_column("bookings", "mechanic_lat")
    op.drop_column("users", "expo_push_token")
