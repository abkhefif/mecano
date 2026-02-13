"""Add ondelete to FKs, Float to Numeric, check constraints, unique constraints, indexes

Revision ID: 006
Revises: 005
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helper: (table, constraint_name, local_col, remote_table, remote_col, ondelete)
# ---------------------------------------------------------------------------
FK_CHANGES = [
    # bookings
    ("bookings", "bookings_buyer_id_fkey", ["buyer_id"], "users", ["id"], "CASCADE"),
    ("bookings", "bookings_mechanic_id_fkey", ["mechanic_id"], "mechanic_profiles", ["id"], "CASCADE"),
    ("bookings", "bookings_availability_id_fkey", ["availability_id"], "availabilities", ["id"], "SET NULL"),
    # reviews
    ("reviews", "reviews_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    ("reviews", "reviews_reviewer_id_fkey", ["reviewer_id"], "users", ["id"], "CASCADE"),
    ("reviews", "reviews_reviewee_id_fkey", ["reviewee_id"], "users", ["id"], "CASCADE"),
    # dispute_cases
    ("dispute_cases", "dispute_cases_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    ("dispute_cases", "dispute_cases_opened_by_fkey", ["opened_by"], "users", ["id"], "CASCADE"),
    ("dispute_cases", "dispute_cases_resolved_by_admin_fkey", ["resolved_by_admin"], "users", ["id"], "CASCADE"),
    # messages
    ("messages", "messages_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    ("messages", "messages_sender_id_fkey", ["sender_id"], "users", ["id"], "CASCADE"),
    # referral_codes
    ("referral_codes", "referral_codes_mechanic_id_fkey", ["mechanic_id"], "mechanic_profiles", ["id"], "CASCADE"),
    # validation_proofs
    ("validation_proofs", "validation_proofs_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    # inspection_checklists
    ("inspection_checklists", "inspection_checklists_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    # reports
    ("reports", "reports_booking_id_fkey", ["booking_id"], "bookings", ["id"], "CASCADE"),
    # availabilities
    ("availabilities", "availabilities_mechanic_id_fkey", ["mechanic_id"], "mechanic_profiles", ["id"], "CASCADE"),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Foreign key ondelete changes
    # ------------------------------------------------------------------
    for table, fk_name, local_cols, ref_table, ref_cols, ondelete in FK_CHANGES:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(fk_name, table, ref_table, local_cols, ref_cols, ondelete=ondelete)

    # ------------------------------------------------------------------
    # 2. Float → Numeric type changes
    # ------------------------------------------------------------------
    # bookings
    op.alter_column("bookings", "meeting_lat",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=False)
    op.alter_column("bookings", "meeting_lng",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=False)
    op.alter_column("bookings", "distance_km",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(6, 2),
                    existing_nullable=False)

    # mechanic_profiles
    op.alter_column("mechanic_profiles", "city_lat",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=False)
    op.alter_column("mechanic_profiles", "city_lng",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=False)
    op.alter_column("mechanic_profiles", "rating_avg",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(3, 2),
                    existing_nullable=True)

    # validation_proofs
    op.alter_column("validation_proofs", "gps_lat",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=True)
    op.alter_column("validation_proofs", "gps_lng",
                    existing_type=sa.Float(),
                    type_=sa.Numeric(9, 6),
                    existing_nullable=True)

    # ------------------------------------------------------------------
    # 3. Check constraints
    # ------------------------------------------------------------------
    op.create_check_constraint("ck_review_rating_range", "reviews",
                               "rating >= 1 AND rating <= 5")
    op.create_check_constraint("ck_booking_base_price_positive", "bookings",
                               "base_price >= 0")
    op.create_check_constraint("ck_booking_total_price_positive", "bookings",
                               "total_price >= 0")
    op.create_check_constraint("ck_booking_commission_rate_range", "bookings",
                               "commission_rate >= 0 AND commission_rate <= 1")

    # ------------------------------------------------------------------
    # 4. Unique constraint on availabilities
    # ------------------------------------------------------------------
    op.create_unique_constraint("uq_availability_mechanic_date_time",
                                "availabilities",
                                ["mechanic_id", "date", "start_time"])

    # ------------------------------------------------------------------
    # 5. Composite indexes on bookings
    # ------------------------------------------------------------------
    op.create_index("ix_bookings_buyer_status_created",
                    "bookings",
                    ["buyer_id", "status", "created_at"])
    op.create_index("ix_bookings_mechanic_status_created",
                    "bookings",
                    ["mechanic_id", "status", "created_at"])

    # ------------------------------------------------------------------
    # 6. Index on reviews.booking_id
    # ------------------------------------------------------------------
    op.create_index("ix_reviews_booking_id", "reviews", ["booking_id"])


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 6. Drop index on reviews.booking_id
    # ------------------------------------------------------------------
    op.drop_index("ix_reviews_booking_id", table_name="reviews")

    # ------------------------------------------------------------------
    # 5. Drop composite indexes on bookings
    # ------------------------------------------------------------------
    op.drop_index("ix_bookings_mechanic_status_created", table_name="bookings")
    op.drop_index("ix_bookings_buyer_status_created", table_name="bookings")

    # ------------------------------------------------------------------
    # 4. Drop unique constraint on availabilities
    # ------------------------------------------------------------------
    op.drop_constraint("uq_availability_mechanic_date_time", "availabilities", type_="unique")

    # ------------------------------------------------------------------
    # 3. Drop check constraints
    # ------------------------------------------------------------------
    op.drop_constraint("ck_booking_commission_rate_range", "bookings", type_="check")
    op.drop_constraint("ck_booking_total_price_positive", "bookings", type_="check")
    op.drop_constraint("ck_booking_base_price_positive", "bookings", type_="check")
    op.drop_constraint("ck_review_rating_range", "reviews", type_="check")

    # ------------------------------------------------------------------
    # 2. Numeric → Float type changes (reverse)
    # ------------------------------------------------------------------
    # validation_proofs
    op.alter_column("validation_proofs", "gps_lng",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=True)
    op.alter_column("validation_proofs", "gps_lat",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=True)

    # mechanic_profiles
    op.alter_column("mechanic_profiles", "rating_avg",
                    existing_type=sa.Numeric(3, 2),
                    type_=sa.Float(),
                    existing_nullable=True)
    op.alter_column("mechanic_profiles", "city_lng",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=False)
    op.alter_column("mechanic_profiles", "city_lat",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=False)

    # bookings
    op.alter_column("bookings", "distance_km",
                    existing_type=sa.Numeric(6, 2),
                    type_=sa.Float(),
                    existing_nullable=False)
    op.alter_column("bookings", "meeting_lng",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=False)
    op.alter_column("bookings", "meeting_lat",
                    existing_type=sa.Numeric(9, 6),
                    type_=sa.Float(),
                    existing_nullable=False)

    # ------------------------------------------------------------------
    # 1. Revert foreign key ondelete (remove ondelete by recreating without it)
    # ------------------------------------------------------------------
    for table, fk_name, local_cols, ref_table, ref_cols, _ondelete in reversed(FK_CHANGES):
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(fk_name, table, ref_table, local_cols, ref_cols)
