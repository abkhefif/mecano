import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DemandStatus, VehicleType


class DemandCreateRequest(BaseModel):
    """Request body for creating a buyer demand."""

    vehicle_type: VehicleType
    vehicle_brand: str = Field(min_length=1, max_length=100)
    vehicle_model: str = Field(min_length=1, max_length=100)
    vehicle_year: int = Field(ge=1950)
    vehicle_plate: str | None = Field(None, max_length=20)

    meeting_address: str = Field(min_length=1, max_length=500)
    meeting_lat: float = Field(ge=-90.0, le=90.0)
    meeting_lng: float = Field(ge=-180.0, le=180.0)

    desired_date: date
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM format")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM format")

    obd_requested: bool = False
    message: str | None = Field(None, max_length=1000)

    @field_validator("vehicle_year")
    @classmethod
    def validate_vehicle_year(cls, v: int) -> int:
        from datetime import datetime as _dt

        max_year = _dt.now().year + 1
        if v > max_year:
            raise ValueError(f"vehicle_year must be at most {max_year}")
        return v

    @field_validator("end_time")
    @classmethod
    def validate_end_after_start(cls, end_time: str, info) -> str:
        start_time = info.data.get("start_time")
        if start_time and end_time:
            start = time.fromisoformat(start_time)
            end = time.fromisoformat(end_time)
            if end <= start:
                raise ValueError("end_time must be after start_time")
        return end_time


class DemandResponse(BaseModel):
    """Response shape for a buyer demand."""

    id: uuid.UUID
    buyer_id: uuid.UUID
    vehicle_type: VehicleType
    vehicle_brand: str
    vehicle_model: str
    vehicle_year: int
    vehicle_plate: str | None
    meeting_address: str
    meeting_lat: float
    meeting_lng: float
    desired_date: date
    start_time: time
    end_time: time
    obd_requested: bool
    message: str | None
    status: DemandStatus
    created_at: datetime
    expires_at: datetime

    # Enriched fields (populated at query time)
    interest_count: int = 0
    buyer_name: str | None = None
    distance_km: float | None = None

    model_config = {"from_attributes": True}


class DemandInterestResponse(BaseModel):
    """Response shape for a mechanic's interest in a demand."""

    id: uuid.UUID
    demand_id: uuid.UUID
    mechanic_id: uuid.UUID
    proposal_id: uuid.UUID | None
    created_at: datetime

    # Enriched mechanic info
    mechanic_name: str | None = None
    mechanic_city: str | None = None
    mechanic_rating: float | None = None

    model_config = {"from_attributes": True}
