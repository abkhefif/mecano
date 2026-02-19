"""Add CHECK constraint on mechanic_profiles.rating_avg BETWEEN 0 AND 5

AUDIT-FIX10: Prevent invalid rating averages from being stored.
rating_avg must be between 0.00 and 5.00 (inclusive).

Revision ID: 028
Revises: 027
Create Date: 2026-02-19 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_mechanic_profiles_rating_avg_range",
        "mechanic_profiles",
        "rating_avg >= 0 AND rating_avg <= 5",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_mechanic_profiles_rating_avg_range",
        "mechanic_profiles",
        type_="check",
    )
