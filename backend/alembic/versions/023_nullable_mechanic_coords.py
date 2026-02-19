"""Make mechanic_profiles city_lat and city_lng nullable

I-001: MechanicProfile was created with city_lat=0.0, city_lng=0.0
(Null Island, Gulf of Guinea) during registration. Now these columns
are nullable so that a freshly-registered mechanic has NULL coordinates
until they set their city.

Revision ID: 023
Revises: 022
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "mechanic_profiles",
        "city_lat",
        existing_type=sa.Numeric(9, 6),
        nullable=True,
    )
    op.alter_column(
        "mechanic_profiles",
        "city_lng",
        existing_type=sa.Numeric(9, 6),
        nullable=True,
    )


def downgrade() -> None:
    # Restore NOT NULL with default 0.0 for any existing NULL rows
    op.execute("UPDATE mechanic_profiles SET city_lat = 0.0 WHERE city_lat IS NULL")
    op.execute("UPDATE mechanic_profiles SET city_lng = 0.0 WHERE city_lng IS NULL")
    op.alter_column(
        "mechanic_profiles",
        "city_lat",
        existing_type=sa.Numeric(9, 6),
        nullable=False,
    )
    op.alter_column(
        "mechanic_profiles",
        "city_lng",
        existing_type=sa.Numeric(9, 6),
        nullable=False,
    )
