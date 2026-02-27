import uuid
from datetime import datetime, timezone, timedelta

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.blacklisted_token import BlacklistedToken
from app.models.enums import UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User

logger = structlog.get_logger()
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT token, return the authenticated user."""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        # Only accept access tokens, not refresh or email_verify tokens
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        # C-03: Check if the token's jti has been blacklisted (logout)
        # TODO F-018: Cache blacklist lookups in Redis (SISMEMBER) to avoid a DB
        # query on every authenticated request.  Acceptable for MVP since access
        # tokens have a short 15-min expiry and the blacklist table stays small.
        jti = payload.get("jti")
        # I-003: Reject tokens that lack a jti claim to prevent blacklist bypass
        if not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        blacklisted = await db.execute(
            select(BlacklistedToken).where(BlacklistedToken.jti == jti)
        )
        if blacklisted.scalar_one_or_none():
            logger.warning("blacklisted_token_used", jti=jti, user_id=str(user_id))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # AUDIT-12: Block deactivated users at the auth level
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deactivated. Contact support for more information.",
        )

    # SEC-005: Reject tokens issued before the last password change.
    # This invalidates ALL sessions across all devices when a password is changed.
    if user.password_changed_at:
        token_iat = payload.get("iat")
        if token_iat:
            # Add 500ms tolerance for clock skew between token issuance and DB write
            issued_at = datetime.fromtimestamp(token_iat, tz=timezone.utc)
            if issued_at < user.password_changed_at - timedelta(milliseconds=500):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token invalidated by password change",
                )

    return user


async def get_current_mechanic(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, MechanicProfile]:
    """Get current user and verify they are a mechanic with a profile."""
    if user.role != UserRole.MECHANIC:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only mechanics can access this resource",
        )

    result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mechanic profile not found",
        )

    if profile.suspended_until and profile.suspended_until > datetime.now(timezone.utc):
        # SEC-008: Generic message — do not leak exact suspension timestamp
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Contact support for more information.",
        )

    return user, profile


async def get_current_buyer(
    user: User = Depends(get_current_user),
) -> User:
    """Get current user and verify they are a buyer."""
    if user.role != UserRole.BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only buyers can access this resource",
        )
    return user


async def get_verified_buyer(
    user: User = Depends(get_current_buyer),
) -> User:
    """Get current buyer and verify their email is verified."""
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Please verify your email before proceeding.",
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Get current user and verify they are an admin."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
