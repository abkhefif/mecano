from decimal import Decimal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://emecano:emecano_password@localhost:5432/emecano"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str  # Required — no default, must be set in .env
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

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

    # App
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    CORS_ORIGINS: str = ""

    # Business rules
    BASE_INSPECTION_PRICE: Decimal = Decimal("50.00")
    PLATFORM_COMMISSION_RATE: Decimal = Decimal("0.20")
    TRAVEL_FEE_PER_KM: Decimal = Decimal("0.30")
    DEFAULT_FREE_ZONE_KM: int = 10
    PAYMENT_RELEASE_DELAY_HOURS: int = 2
    MECHANIC_ACCEPTANCE_TIMEOUT_HOURS: int = 2

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
