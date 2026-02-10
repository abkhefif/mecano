import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import UploadedBy
from app.models.types import GUID


class ValidationProof(Base):
    __tablename__ = "validation_proofs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bookings.id"), unique=True, nullable=False
    )
    photo_plate_url: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_odometer_url: Mapped[str] = mapped_column(String(500), nullable=False)
    entered_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    entered_odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_by: Mapped[UploadedBy] = mapped_column(String(20), nullable=False)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="validation_proof")
