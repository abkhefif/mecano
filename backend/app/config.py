import warnings
from decimal import Decimal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_WEAK_SECRETS = {"changeme", "change-me", "secret", "change-this-to-a-long-random-string-in-production"}

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://emecano:emecano_password@localhost:5432/emecano"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = _DEFAULT_DATABASE_URL

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str  # Required — no default, must be set in .env
    JWT_ALGORITHM: str = "HS256"

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        if v.lower() in _WEAK_SECRETS:
            raise ValueError("JWT_SECRET is using a known weak default — generate a proper random secret")
        return v
    # SEC-025: OWASP recommends 5 minutes for access tokens, but 15 minutes is
    # chosen for UX reasons — mobile app users on slow networks would face
    # excessive re-authentication with a shorter window.
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # R2 / S3
    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "emecano-storage"
    R2_PUBLIC_URL: str = ""

    # Stripe Connect URLs
    STRIPE_REFRESH_URL: str = "https://emecano.fr/stripe/refresh"
    STRIPE_RETURN_URL: str = "https://emecano.fr/stripe/return"

    # Resend (email)
    RESEND_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:8081"

    # Sentry
    SENTRY_DSN: str = ""

    # App
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    CORS_ORIGINS: str = ""

    # Business rules
    BASE_INSPECTION_PRICE: Decimal = Decimal("40.00")
    OBD_SUPPLEMENT: Decimal = Decimal("25.00")
    PLATFORM_COMMISSION_RATE: Decimal = Decimal("0.20")
    TRAVEL_FEE_PER_KM: Decimal = Decimal("0.30")
    DEFAULT_FREE_ZONE_KM: int = 10
    PAYMENT_RELEASE_DELAY_HOURS: int = 2
    MECHANIC_ACCEPTANCE_TIMEOUT_HOURS: int = 2

    # Booking constants
    BOOKING_SLOT_DURATION_MINUTES: int = 30
    BOOKING_BUFFER_ZONE_MINUTES: int = 15
    BOOKING_MINIMUM_ADVANCE_HOURS: int = 2
    BOOKING_CHECK_IN_TOLERANCE_MINUTES: int = 30
    MAX_CHECK_IN_CODE_ATTEMPTS: int = 5
    CANCELLATION_FULL_REFUND_HOURS: int = 24
    CANCELLATION_PARTIAL_REFUND_HOURS: int = 12

    @model_validator(mode="after")
    def normalize_database_url(self) -> "Settings":
        """Convert postgres:// to postgresql+asyncpg:// for Render compatibility."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            self.DATABASE_URL = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            self.DATABASE_URL = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Warn in development but fail in production for insecure defaults."""
        if self.is_production:
            if self.DATABASE_URL == _DEFAULT_DATABASE_URL:
                raise ValueError(
                    "DATABASE_URL is using the default development credentials. "
                    "Set a secure DATABASE_URL in production."
                )
            if not self.STRIPE_SECRET_KEY:
                raise ValueError(
                    "STRIPE_SECRET_KEY must be set in production."
                )
            if not self.STRIPE_WEBHOOK_SECRET:
                raise ValueError(
                    "STRIPE_WEBHOOK_SECRET must be set in production."
                )
        else:
            if self.DATABASE_URL == _DEFAULT_DATABASE_URL:
                warnings.warn(
                    "DATABASE_URL is using default development credentials. "
                    "Do not use these in production.",
                    stacklevel=2,
                )
            if not self.STRIPE_SECRET_KEY:
                warnings.warn(
                    "STRIPE_SECRET_KEY is empty — Stripe calls will be mocked.",
                    stacklevel=2,
                )
            if not self.STRIPE_WEBHOOK_SECRET:
                warnings.warn(
                    "STRIPE_WEBHOOK_SECRET is empty — webhook verification will be insecure.",
                    stacklevel=2,
                )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
