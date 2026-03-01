import hashlib
import hmac
import secrets

from app.config import settings


def generate_check_in_code() -> str:
    """Generate a random 6-digit code for check-in validation."""
    return f"{secrets.randbelow(1000000):06d}"


def hash_check_in_code(code: str) -> str:
    """Hash a check-in code with HMAC-SHA-256 + dedicated secret key.

    HIGH-02: The fallback to JWT_SECRET has been removed.  If CHECK_IN_HMAC_KEY
    is not configured the function raises RuntimeError so the misconfiguration is
    caught immediately rather than silently reusing the JWT signing key.
    """
    key = settings.CHECK_IN_HMAC_KEY
    if not key:
        raise RuntimeError(
            "CHECK_IN_HMAC_KEY is not configured. "
            "Set a dedicated HMAC key to keep check-in codes cryptographically separate from JWT tokens."
        )
    return hmac.new(key.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_check_in_code(code: str, code_hash: str) -> bool:
    """Verify a check-in code against its hash (constant-time comparison)."""
    return secrets.compare_digest(hash_check_in_code(code), code_hash)
