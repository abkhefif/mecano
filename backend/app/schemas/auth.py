import re
import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole

_NAME_PATTERN = re.compile(r"^[a-zA-ZÀ-ÿ\s\-']+$")


def validate_name_field(v: str | None, field_label: str) -> str | None:
    """Validate a name field: min 3 chars, alphabetic only (accents, hyphens, apostrophes allowed)."""
    if v is None:
        return v
    v = v.strip()
    if not v:
        return None
    if len(v) < 3:
        raise ValueError(f"{field_label} doit contenir au moins 3 caractères")
    if not _NAME_PATTERN.match(v):
        raise ValueError(f"{field_label} ne doit contenir que des lettres, espaces, tirets ou apostrophes")
    return v


def validate_password_complexity(password: str) -> str:
    """Validate password contains at least one uppercase, one lowercase, and one digit."""
    if not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("Le mot de passe doit contenir au moins une majuscule, une minuscule et un chiffre")
    return password


class RegistrationRole(str, Enum):
    BUYER = "buyer"
    MECHANIC = "mechanic"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: RegistrationRole
    first_name: str | None = Field(None, min_length=3, max_length=100)
    last_name: str | None = Field(None, min_length=3, max_length=100)
    phone: str | None = Field(None, pattern=r"^\+?[0-9]{10,15}$")
    referral_code: str | None = Field(None, max_length=20)
    cgu_accepted: bool = Field(False, validate_default=True)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Le prénom")

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Le nom")

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)

    @field_validator("cgu_accepted")
    @classmethod
    def cgu_must_be_accepted(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Vous devez accepter les CGU pour créer un compte")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


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
    photo_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MechanicProfileResponse(BaseModel):
    id: uuid.UUID
    city: str
    city_lat: float | None = None
    city_lng: float | None = None
    max_radius_km: int
    free_zone_km: int
    accepted_vehicle_types: list[str]
    rating_avg: float
    total_reviews: int
    is_identity_verified: bool
    has_cv: bool
    has_obd_diagnostic: bool
    photo_url: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(None, min_length=3, max_length=100)
    last_name: str | None = Field(None, min_length=3, max_length=100)
    # L-01: Add phone pattern validation matching RegisterRequest
    phone: str | None = Field(None, pattern=r"^\+?[0-9]{10,15}$")

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Le prénom")

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Le nom")


class UserWithProfileResponse(UserResponse):
    mechanic_profile: MechanicProfileResponse | None = None


class PushTokenRequest(BaseModel):
    token: str = Field(max_length=100)

    @field_validator("token")
    @classmethod
    def validate_expo_token_format(cls, v: str) -> str:
        import re
        if not re.match(r"^ExponentPushToken\[.+\]$", v):
            raise ValueError("Token must be a valid Expo push token (ExponentPushToken[...])")
        return v


class EmailVerifyRequest(BaseModel):
    token: str | None = None
    code: str | None = Field(None, pattern=r"^\d{6}$")
    email: EmailStr | None = None

    @field_validator("code")
    @classmethod
    def validate_code_requires_email(cls, v: str | None, info) -> str | None:
        # Validation is done at model level in model_validator
        return v

    def model_post_init(self, __context) -> None:
        if not self.token and not (self.code and self.email):
            raise ValueError("Either 'token' or both 'code' and 'email' are required")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(max_length=2048)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_complexity(v)


class MessageResponse(BaseModel):
    message: str
