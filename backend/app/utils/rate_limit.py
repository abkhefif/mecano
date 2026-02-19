from starlette.requests import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

import os


def get_real_ip(request: Request) -> str:
    """Extract the real client IP, respecting TRUSTED_PROXY_COUNT.

    AUD-001: When TRUSTED_PROXY_COUNT is 0 (default), ignore X-Forwarded-For
    entirely and use the direct connection IP. When > 0, pick the IP at position
    len(ips) - trusted_proxy_count from X-Forwarded-For to prevent spoofing.
    """
    trusted_proxy_count = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",")]
            index = max(0, len(ips) - trusted_proxy_count)
            return ips[index]
    return get_remote_address(request)


def _get_storage_uri():
    """AUD-C02: Use Redis for rate limiting when REDIS_URL is configured in production.

    Uses lazy import to avoid circular imports with app.config.settings.
    """
    try:
        from app.config import settings
        if settings.REDIS_URL and "localhost" not in settings.REDIS_URL:
            return settings.REDIS_URL
    except Exception:
        pass
    return None


_is_dev = os.getenv("APP_ENV", "development") == "development"

limiter = Limiter(
    key_func=get_real_ip,
    storage_uri=_get_storage_uri(),
    default_limits=["200/minute" if _is_dev else "60/minute"],
)

# Per-endpoint rate limit decorators for sensitive operations
AUTH_RATE_LIMIT = "30/minute" if _is_dev else "5/minute"
CODE_ENTRY_RATE_LIMIT = "10/minute" if _is_dev else "3/minute"
# SEC-016: Moderate rate limit for list/search endpoints to prevent scraping
LIST_RATE_LIMIT = "100/minute" if _is_dev else "30/minute"
