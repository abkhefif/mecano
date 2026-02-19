"""Add CHECK constraint ensuring gps_lat and gps_lng are both NULL or both set

R-004: ValidationProof GPS coordinates must be both present or both absent.

Revision ID: 022
Revises: 021
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_validation_proof_gps_both_or_neither",
        "validation_proofs",
        "(gps_lat IS NULL) = (gps_lng IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_validation_proof_gps_both_or_neither", "validation_proofs", type_="check")
