import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import (
    BatteryStatus,
    BodyStatus,
    ComponentStatus,
    DriveBehavior,
    ExhaustStatus,
    FluidStatus,
    LightStatus,
    Recommendation,
    SuspensionStatus,
)
from app.models.types import GUID


class InspectionChecklist(Base):
    __tablename__ = "inspection_checklists"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("bookings.id"), unique=True, nullable=False
    )
    brakes: Mapped[ComponentStatus] = mapped_column(String(20), nullable=False)
    tires: Mapped[ComponentStatus] = mapped_column(String(20), nullable=False)
    fluids: Mapped[FluidStatus] = mapped_column(String(20), nullable=False)
    battery: Mapped[BatteryStatus] = mapped_column(String(20), nullable=False)
    suspension: Mapped[SuspensionStatus] = mapped_column(String(20), nullable=False)
    body: Mapped[BodyStatus] = mapped_column(String(20), nullable=False)
    exhaust: Mapped[ExhaustStatus] = mapped_column(String(20), nullable=False)
    lights: Mapped[LightStatus] = mapped_column(String(20), nullable=False)
    test_drive_done: Mapped[bool] = mapped_column(Boolean, nullable=False)
    test_drive_behavior: Mapped[DriveBehavior | None] = mapped_column(String(20), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[Recommendation] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped["Booking"] = relationship("Booking", back_populates="inspection_checklist")
