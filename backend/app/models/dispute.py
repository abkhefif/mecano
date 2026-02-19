import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DisputeReason, DisputeStatus
from app.models.types import GUID


class DisputeCase(Base):
    __tablename__ = "dispute_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved_buyer', 'resolved_mechanic', 'closed')",
            name="ck_dispute_cases_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    opened_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[DisputeReason] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    photo_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[DisputeStatus] = mapped_column(
        String(20), nullable=False, default=DisputeStatus.OPEN
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_admin: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped["Booking"] = relationship("Booking", back_populates="dispute")
    opener: Mapped["User | None"] = relationship("User", foreign_keys=[opened_by])
    admin: Mapped["User | None"] = relationship("User", foreign_keys=[resolved_by_admin])
