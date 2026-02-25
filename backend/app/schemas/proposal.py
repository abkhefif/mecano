import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ProposalStatus, VehicleType


class ProposalCreateRequest(BaseModel):
    mechanic_id: uuid.UUID
    proposed_date: date
    proposed_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM")
    message: str | None = Field(None, max_length=500)
    vehicle_type: VehicleType
    vehicle_brand: str = Field(min_length=1, max_length=100)
    vehicle_model: str = Field(min_length=1, max_length=100)
    vehicle_year: int = Field(ge=1950)

    @field_validator("vehicle_year")
    @classmethod
    def validate_vehicle_year(cls, v: int) -> int:
        max_year = datetime.now().year + 1
        if v > max_year:
            raise ValueError(f"vehicle_year must be at most {max_year}")
        return v

    vehicle_plate: str | None = Field(None, max_length=20)
    meeting_address: str = Field(min_length=1, max_length=500)
    meeting_lat: float = Field(ge=-90, le=90)
    meeting_lng: float = Field(ge=-180, le=180)
    obd_requested: bool = False


class ProposalCounterRequest(BaseModel):
    proposed_date: date
    proposed_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM")
    message: str | None = Field(None, max_length=500)


class ProposalResponse(BaseModel):
    id: uuid.UUID
    buyer_id: uuid.UUID
    mechanic_id: uuid.UUID
    proposed_date: date
    proposed_time: str
    message: str | None
    status: ProposalStatus
    round_number: int
    parent_id: uuid.UUID | None
    responded_by: str | None
    booking_id: uuid.UUID | None
    vehicle_type: VehicleType
    vehicle_brand: str
    vehicle_model: str
    vehicle_year: int
    vehicle_plate: str | None
    meeting_address: str
    meeting_lat: float
    meeting_lng: float
    obd_requested: bool
    created_at: datetime
    expires_at: datetime
    buyer_name: str | None = None
    mechanic_name: str | None = None

    model_config = {"from_attributes": True}


class ProposalHistoryResponse(BaseModel):
    current: ProposalResponse
    history: list[ProposalResponse]
