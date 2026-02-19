"""Widen rating_avg from Numeric(3,2) to Numeric(4,2)

I-005: Numeric(3,2) caps the maximum value at 9.99 which could overflow
if a calculation bug produced a value >= 10. Numeric(4,2) allows values
up to 99.99, providing a safety margin while keeping the 2 decimal places.

Revision ID: 024
Revises: 023
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "mechanic_profiles",
        "rating_avg",
        existing_type=sa.Numeric(3, 2),
        type_=sa.Numeric(4, 2),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "mechanic_profiles",
        "rating_avg",
        existing_type=sa.Numeric(4, 2),
        type_=sa.Numeric(3, 2),
        existing_nullable=True,
    )
