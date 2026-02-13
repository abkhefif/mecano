import uuid
from datetime import date, datetime, time, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import VehicleType


class DiplomaResponse(BaseModel):
    id: uuid.UUID
    name: str
    year: int | None = None
    document_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MechanicUpdateRequest(BaseModel):
    city: str | None = Field(None, max_length=100)
    city_lat: float | None = Field(None, ge=-90, le=90)
    city_lng: float | None = Field(None, ge=-180, le=180)
    max_radius_km: int | None = Field(None, ge=10, le=50)
    free_zone_km: int | None = Field(None, ge=0, le=50)
    accepted_vehicle_types: list[VehicleType] | None = None
    has_obd_diagnostic: bool | None = None

    @model_validator(mode="after")
    def free_zone_within_radius(self) -> "MechanicUpdateRequest":
        if self.free_zone_km is not None and self.max_radius_km is not None:
            if self.free_zone_km > self.max_radius_km:
                raise ValueError("free_zone_km must be less than or equal to max_radius_km")
        return self


class MechanicListItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    city: str
    city_lat: float
    city_lng: float
    distance_km: float | None = None
    max_radius_km: int
    accepted_vehicle_types: list[str]
    rating_avg: float
    total_reviews: int
    has_cv: bool
    has_obd_diagnostic: bool
    is_identity_verified: bool
    photo_url: str | None = None
    next_available_date: str | None = None

    model_config = {"from_attributes": True}


class MechanicDetailResponse(MechanicListItem):
    free_zone_km: int
    city_lat: float
    city_lng: float
    cv_url: str | None = None


class ReviewSummary(BaseModel):
    id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
    reviewer_name: str | None = None

    model_config = {"from_attributes": True}


class AvailabilityResponse(BaseModel):
    id: uuid.UUID
    mechanic_id: uuid.UUID
    date: date
    start_time: time
    end_time: time
    is_booked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MechanicDetailWithSlots(BaseModel):
    profile: MechanicDetailResponse
    reviews: list[ReviewSummary]
    availabilities: list[AvailabilityResponse]
    diplomas: list[DiplomaResponse] = []


class AvailabilityCreateRequest(BaseModel):
    date: date
    start_time: time
    end_time: time

    @field_validator("date")
    @classmethod
    def date_not_in_past(cls, v: date) -> date:
        if v < datetime.now(timezone.utc).date():
            raise ValueError("Date must be today or in the future")
        return v
