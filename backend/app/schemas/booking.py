import uuid
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    BatteryStatus,
    BodyStatus,
    BookingStatus,
    ComponentStatus,
    DisputeReason,
    DriveBehavior,
    ExhaustStatus,
    FluidStatus,
    LightStatus,
    Recommendation,
    RefusalReason,
    SuspensionStatus,
    VehicleType,
)


class BookingCreateRequest(BaseModel):
    mechanic_id: uuid.UUID
    availability_id: uuid.UUID
    vehicle_type: VehicleType
    vehicle_brand: str = Field(max_length=100)
    vehicle_model: str = Field(max_length=100)
    vehicle_year: int = Field(ge=1950)

    @field_validator("vehicle_year")
    @classmethod
    def validate_vehicle_year(cls, v: int) -> int:
        max_year = datetime.now().year + 1
        if v > max_year:
            raise ValueError(f"vehicle_year must be at most {max_year}")
        return v
    vehicle_plate: str | None = Field(None, max_length=20)
    obd_requested: bool = False
    meeting_address: str = Field(max_length=500)
    meeting_lat: float = Field(ge=-90, le=90)
    meeting_lng: float = Field(ge=-180, le=180)
    slot_start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$", description="Chosen sub-slot start time HH:MM within the availability window")


class BookingResponse(BaseModel):
    """Full booking response (admin view)."""
    id: uuid.UUID
    buyer_id: uuid.UUID
    mechanic_id: uuid.UUID
    availability_id: uuid.UUID | None
    status: BookingStatus
    vehicle_type: VehicleType
    vehicle_brand: str
    vehicle_model: str
    vehicle_year: int
    vehicle_plate: str | None
    meeting_address: str
    distance_km: float
    obd_requested: bool
    base_price: Decimal
    travel_fees: Decimal
    total_price: Decimal
    commission_amount: Decimal
    mechanic_payout: Decimal
    check_in_at: datetime | None
    check_out_at: datetime | None
    payment_released_at: datetime | None
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: str | None = None
    refund_percentage: int | None = None
    refund_amount: Decimal | None = None

    model_config = {"from_attributes": True}


class BookingBuyerResponse(BaseModel):
    """Booking response for buyers — hides commission details."""
    id: uuid.UUID
    buyer_id: uuid.UUID
    mechanic_id: uuid.UUID
    availability_id: uuid.UUID | None
    status: BookingStatus
    vehicle_type: VehicleType
    vehicle_brand: str
    vehicle_model: str
    vehicle_year: int
    vehicle_plate: str | None
    meeting_address: str
    distance_km: float
    obd_requested: bool
    base_price: Decimal
    travel_fees: Decimal
    total_price: Decimal
    check_in_at: datetime | None
    check_out_at: datetime | None
    payment_released_at: datetime | None
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: str | None = None
    refund_percentage: int | None = None
    refund_amount: Decimal | None = None

    model_config = {"from_attributes": True}


class BookingMechanicResponse(BaseModel):
    """Booking response for mechanics — shows payout, hides total/commission."""
    id: uuid.UUID
    buyer_id: uuid.UUID
    mechanic_id: uuid.UUID
    availability_id: uuid.UUID | None
    status: BookingStatus
    vehicle_type: VehicleType
    vehicle_brand: str
    vehicle_model: str
    vehicle_year: int
    vehicle_plate: str | None
    meeting_address: str
    distance_km: float
    obd_requested: bool
    base_price: Decimal
    travel_fees: Decimal
    mechanic_payout: Decimal
    check_in_at: datetime | None
    check_out_at: datetime | None
    payment_released_at: datetime | None
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: str | None = None
    refund_percentage: int | None = None
    refund_amount: Decimal | None = None

    model_config = {"from_attributes": True}


class BookingCreateResponse(BaseModel):
    booking: BookingResponse
    client_secret: str | None = None


class RefuseRequest(BaseModel):
    reason: RefusalReason
    proposed_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$", description="Alternative time HH:MM the mechanic proposes")


class CheckInRequest(BaseModel):
    mechanic_present: bool


class CheckInResponse(BaseModel):
    check_in_code: str | None = None
    dispute_opened: bool = False
    # H-01: Warning flag when mechanic GPS is near the meeting point during no-show report
    mechanic_nearby_warning: bool = False


class EnterCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class ChecklistInput(BaseModel):
    brakes: ComponentStatus
    tires: ComponentStatus
    fluids: FluidStatus
    battery: BatteryStatus
    suspension: SuspensionStatus
    body: BodyStatus
    exhaust: ExhaustStatus
    lights: LightStatus
    test_drive_done: bool
    test_drive_behavior: DriveBehavior | None = None
    remarks: str | None = Field(None, max_length=500)
    recommendation: Recommendation


class CheckOutRequest(BaseModel):
    entered_plate: str | None = Field(None, max_length=20)
    entered_odometer_km: int = Field(ge=0)
    gps_lat: float | None = Field(None, ge=-90, le=90)
    gps_lng: float | None = Field(None, ge=-180, le=180)
    checklist: ChecklistInput


class CheckOutResponse(BaseModel):
    pdf_url: str


class LocationUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ValidateRequest(BaseModel):
    validated: bool
    problem_reason: DisputeReason | None = None
    problem_description: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def check_dispute_fields(self):
        if not self.validated:
            if not self.problem_reason:
                raise ValueError("problem_reason is required when validated is False")
            if not self.problem_description:
                raise ValueError("problem_description is required when validated is False")
        return self
