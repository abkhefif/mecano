import hashlib
import hmac
import secrets

from app.config import settings


def generate_check_in_code() -> str:
    """Generate a random 6-digit code for check-in validation."""
    return f"{secrets.randbelow(1000000):06d}"


def hash_check_in_code(code: str) -> str:
    """Hash a check-in code with HMAC-SHA-256 + secret salt."""
    return hmac.new(settings.JWT_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_check_in_code(code: str, code_hash: str) -> bool:
    """Verify a check-in code against its hash (constant-time comparison)."""
    return secrets.compare_digest(hash_check_in_code(code), code_hash)
