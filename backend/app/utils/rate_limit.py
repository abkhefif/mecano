from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# Per-endpoint rate limit decorators for sensitive operations
AUTH_RATE_LIMIT = "5/minute"
CODE_ENTRY_RATE_LIMIT = "3/minute"
