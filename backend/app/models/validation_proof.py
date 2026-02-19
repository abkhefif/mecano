import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import UploadedBy
from app.models.types import GUID


class ValidationProof(Base):
    __tablename__ = "validation_proofs"
    __table_args__ = (
        CheckConstraint(
            "(gps_lat IS NULL) = (gps_lng IS NULL)",
            name="ck_validation_proof_gps_both_or_neither",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    photo_plate_url: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_odometer_url: Mapped[str] = mapped_column(String(500), nullable=False)
    entered_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    entered_odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    # NOTE: lat and lng are independently nullable but must logically be both
    # null or both set. Enforced by ck_validation_proof_gps_both_or_neither
    # (added in migration 022).
    gps_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    additional_photo_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_by: Mapped[UploadedBy] = mapped_column(String(20), nullable=False)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="validation_proof")
