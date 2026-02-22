import hashlib
import secrets

from app.config import settings


def generate_check_in_code() -> str:
    """Generate a random 4-digit code for check-in validation."""
    return f"{secrets.randbelow(10000):04d}"


def hash_check_in_code(code: str) -> str:
    """Hash a check-in code with SHA-256 + secret salt."""
    salted = f"{code}{settings.JWT_SECRET}"
    return hashlib.sha256(salted.encode()).hexdigest()


def verify_check_in_code(code: str, code_hash: str) -> bool:
    """Verify a check-in code against its hash (constant-time comparison)."""
    return secrets.compare_digest(hash_check_in_code(code), code_hash)
