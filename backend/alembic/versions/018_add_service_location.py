"""Add service_location and garage_address columns to mechanic_profiles

Revision ID: 018
Revises: 017
Create Date: 2026-02-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mechanic_profiles",
        sa.Column("service_location", sa.String(20), nullable=False, server_default="mobile"),
    )
    op.add_column(
        "mechanic_profiles",
        sa.Column("garage_address", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mechanic_profiles", "garage_address")
    op.drop_column("mechanic_profiles", "service_location")
