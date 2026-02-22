"""Hash existing plaintext check-in codes

H-002: Check-in codes were stored in plaintext. This migration hashes all
existing plaintext codes using SHA-256 + JWT_SECRET salt to match the new
hash_check_in_code() format.

Detection: plaintext codes are exactly 4 digits (length 4).
Hashed codes are 64-char hex strings (SHA-256 output).

Revision ID: 032
Revises: 031
Create Date: 2026-02-22
"""

import hashlib
import logging

from alembic import op
from sqlalchemy import text

from app.config import settings

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic")


def _hash_code(code: str) -> str:
    """Hash a check-in code with SHA-256 + JWT_SECRET salt (same as code_generator.py)."""
    salted = f"{code}{settings.JWT_SECRET}"
    return hashlib.sha256(salted.encode()).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()

    # Find all bookings with plaintext check-in codes (4 chars = not yet hashed)
    # Hashed codes are 64 chars (SHA-256 hex digest)
    result = conn.execute(
        text(
            "SELECT id, check_in_code FROM bookings "
            "WHERE check_in_code IS NOT NULL AND length(check_in_code) = 4"
        )
    )
    rows = result.fetchall()

    if not rows:
        logger.info("No plaintext check-in codes found — nothing to migrate.")
        return

    logger.info("Hashing %d plaintext check-in codes...", len(rows))

    for row in rows:
        booking_id, plaintext_code = row
        hashed = _hash_code(plaintext_code)
        conn.execute(
            text("UPDATE bookings SET check_in_code = :hashed WHERE id = :bid"),
            {"hashed": hashed, "bid": booking_id},
        )

    logger.info("Done — %d codes hashed successfully.", len(rows))


def downgrade() -> None:
    # Irreversible: we cannot recover plaintext codes from hashes
    logger.warning(
        "Downgrade: hashed check-in codes cannot be reverted to plaintext. "
        "Affected bookings will need new codes generated."
    )
