"""Add photo_url to mechanic_profiles and create diplomas table

Revision ID: 009
Revises: 008
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mechanic_profiles",
        sa.Column("photo_url", sa.String(500), nullable=True),
    )

    op.create_table(
        "diplomas",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mechanic_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("mechanic_profiles.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_diplomas_mechanic_id", "diplomas", ["mechanic_id"])


def downgrade() -> None:
    op.drop_table("diplomas")
    op.drop_column("mechanic_profiles", "photo_url")
