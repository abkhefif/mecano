from slowapi import Limiter
from slowapi.util import get_remote_address

import os

_is_dev = os.getenv("APP_ENV", "development") == "development"

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute" if _is_dev else "60/minute"])

# Per-endpoint rate limit decorators for sensitive operations
AUTH_RATE_LIMIT = "30/minute" if _is_dev else "5/minute"
CODE_ENTRY_RATE_LIMIT = "10/minute" if _is_dev else "3/minute"
# SEC-016: Moderate rate limit for list/search endpoints to prevent scraping
LIST_RATE_LIMIT = "100/minute" if _is_dev else "30/minute"
