import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole


class RegistrationRole(str, Enum):
    BUYER = "buyer"
    MECHANIC = "mechanic"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: RegistrationRole
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, pattern=r"^\+?[0-9]{10,15}$")

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not any(c.islower() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        if not any(c.isdigit() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    first_name: str | None
    last_name: str | None
    phone: str | None
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MechanicProfileResponse(BaseModel):
    id: uuid.UUID
    city: str
    city_lat: float
    city_lng: float
    max_radius_km: int
    free_zone_km: int
    accepted_vehicle_types: list[str]
    rating_avg: float
    total_reviews: int
    is_identity_verified: bool
    has_cv: bool
    is_active: bool

    model_config = {"from_attributes": True}


class UserWithProfileResponse(UserResponse):
    mechanic_profile: MechanicProfileResponse | None = None
