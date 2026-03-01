"""Add verification_code_attempts column to users table.

Revision ID: 041
Revises: ee3524af5c26
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "ee3524af5c26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "verification_code_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "verification_code_attempts")
