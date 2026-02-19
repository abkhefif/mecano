import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
import jwt

from app.config import settings

# SEC-017: Bcrypt cost factor 12 (same as previous passlib config)
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Synchronous — used in tests and fixtures."""
    salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return _bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


async def hash_password_async(password: str) -> str:
    """ARCH-002: Async wrapper to avoid blocking the event loop (~300ms per call)."""
    return await asyncio.to_thread(hash_password, password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash. Synchronous — used in tests and fixtures.

    Compatible with both old passlib hashes and new direct-bcrypt hashes
    (both produce standard $2b$ format).
    """
    try:
        return _bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """ARCH-002: Async wrapper to avoid blocking the event loop (~300ms per call)."""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": now,
        "iss": "emecano",
        "type": "access",
        "jti": str(uuid.uuid4()),  # SEC-008: unique token ID for future blacklist support
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": now,
        "iss": "emecano",
        "type": "refresh",
        "jti": str(uuid.uuid4()),  # SEC-008: unique token ID for future blacklist support
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_refresh_token(token: str) -> str | None:
    """Decode a refresh token and return the user_id, or None if invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        if payload.get("type") != "refresh":
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def create_password_reset_token(user_id: str) -> str:
    """Generate a JWT token for password reset (1h expiry)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=1)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": now,
        "iss": "emecano",
        "type": "password_reset",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_password_reset_token(token: str) -> dict | None:
    """Decode a password reset token and return the full payload, or None if invalid.

    Returns a dict with 'sub' (user_id) and 'jti' keys on success.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        if payload.get("type") != "password_reset":
            return None
        return payload
    except jwt.PyJWTError:
        return None
