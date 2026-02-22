"""Data integrity fixes: FK policies, CHECK constraints, indexes

BUG-001: dispute_cases.booking_id CASCADE → RESTRICT
BUG-002: validation_proofs.booking_id CASCADE → RESTRICT
BUG-003: messages.sender_id CASCADE → SET NULL (+ nullable)
BUG-004: CHECK constraints on financial fields
Performance indexes on notifications, dispute_cases, audit_logs, blacklisted_tokens

Revision ID: 030
Revises: 029
Create Date: 2026-02-19 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── BUG-001: dispute_cases.booking_id CASCADE → RESTRICT ──
    op.drop_constraint(
        "dispute_cases_booking_id_fkey", "dispute_cases", type_="foreignkey"
    )
    op.create_foreign_key(
        "dispute_cases_booking_id_fkey",
        "dispute_cases",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ── BUG-002: validation_proofs.booking_id CASCADE → RESTRICT ──
    op.drop_constraint(
        "validation_proofs_booking_id_fkey", "validation_proofs", type_="foreignkey"
    )
    op.create_foreign_key(
        "validation_proofs_booking_id_fkey",
        "validation_proofs",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ── BUG-003: messages.sender_id CASCADE → SET NULL (+ nullable) ──
    op.drop_constraint(
        "messages_sender_id_fkey", "messages", type_="foreignkey"
    )
    op.alter_column("messages", "sender_id", nullable=True)
    op.create_foreign_key(
        "messages_sender_id_fkey",
        "messages",
        "users",
        ["sender_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── BUG-004: CHECK constraints on financial fields ──
    op.create_check_constraint(
        "ck_booking_commission_amount_positive",
        "bookings",
        "commission_amount >= 0",
    )
    op.create_check_constraint(
        "ck_booking_mechanic_payout_positive",
        "bookings",
        "mechanic_payout >= 0",
    )
    op.create_check_constraint(
        "ck_booking_travel_fees_positive",
        "bookings",
        "travel_fees >= 0",
    )
    op.create_check_constraint(
        "ck_booking_refund_amount_positive",
        "bookings",
        "refund_amount >= 0 OR refund_amount IS NULL",
    )
    op.create_check_constraint(
        "ck_booking_refund_percentage_range",
        "bookings",
        "(refund_percentage >= 0 AND refund_percentage <= 100) OR refund_percentage IS NULL",
    )

    # Additional CHECK constraints on other tables
    op.create_check_constraint(
        "ck_validation_proof_odometer_positive",
        "validation_proofs",
        "entered_odometer_km >= 0",
    )
    op.create_check_constraint(
        "ck_mechanic_no_show_count_positive",
        "mechanic_profiles",
        "no_show_count >= 0",
    )
    op.create_check_constraint(
        "ck_referral_uses_count_positive",
        "referral_codes",
        "uses_count >= 0",
    )

    # ── Performance indexes (IF NOT EXISTS to avoid conflicts with earlier migrations) ──
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_user_created ON notifications (user_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_user_is_read ON notifications (user_id, is_read)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dispute_cases_status ON dispute_cases (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_admin_user_id ON audit_logs (admin_user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_blacklisted_tokens_expires_at ON blacklisted_tokens (expires_at)")


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_blacklisted_tokens_expires_at", table_name="blacklisted_tokens")
    op.drop_index("ix_audit_logs_admin_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_dispute_cases_status", table_name="dispute_cases")
    op.drop_index("ix_notification_user_is_read", table_name="notifications")
    op.drop_index("ix_notification_user_created", table_name="notifications")

    # Drop CHECK constraints
    op.drop_constraint("ck_referral_uses_count_positive", "referral_codes", type_="check")
    op.drop_constraint("ck_mechanic_no_show_count_positive", "mechanic_profiles", type_="check")
    op.drop_constraint("ck_validation_proof_odometer_positive", "validation_proofs", type_="check")
    op.drop_constraint("ck_booking_refund_percentage_range", "bookings", type_="check")
    op.drop_constraint("ck_booking_refund_amount_positive", "bookings", type_="check")
    op.drop_constraint("ck_booking_travel_fees_positive", "bookings", type_="check")
    op.drop_constraint("ck_booking_mechanic_payout_positive", "bookings", type_="check")
    op.drop_constraint("ck_booking_commission_amount_positive", "bookings", type_="check")

    # Revert messages.sender_id to CASCADE + non-nullable
    op.drop_constraint("messages_sender_id_fkey", "messages", type_="foreignkey")
    op.alter_column("messages", "sender_id", nullable=False)
    op.create_foreign_key(
        "messages_sender_id_fkey",
        "messages",
        "users",
        ["sender_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Revert validation_proofs.booking_id to CASCADE
    op.drop_constraint(
        "validation_proofs_booking_id_fkey", "validation_proofs", type_="foreignkey"
    )
    op.create_foreign_key(
        "validation_proofs_booking_id_fkey",
        "validation_proofs",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Revert dispute_cases.booking_id to CASCADE
    op.drop_constraint(
        "dispute_cases_booking_id_fkey", "dispute_cases", type_="foreignkey"
    )
    op.create_foreign_key(
        "dispute_cases_booking_id_fkey",
        "dispute_cases",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="CASCADE",
    )
