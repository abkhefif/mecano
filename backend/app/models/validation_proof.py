import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import UploadedBy
from app.models.types import GUID


class ValidationProof(Base):
    __tablename__ = "validation_proofs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    photo_plate_url: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_odometer_url: Mapped[str] = mapped_column(String(500), nullable=False)
    entered_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    entered_odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    # NOTE: lat and lng are independently nullable but should logically be both
    # null or both set. Consider adding a CHECK constraint in a future migration:
    #   CHECK ((gps_lat IS NULL) = (gps_lng IS NULL))
    gps_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_by: Mapped[UploadedBy] = mapped_column(String(20), nullable=False)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="validation_proof")
