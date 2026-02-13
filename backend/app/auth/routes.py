import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.blacklisted_token import BlacklistedToken
from app.models.enums import UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.referral import ReferralCode
from app.models.user import User
from app.schemas.auth import (
    EmailVerifyRequest,
    LoginRequest,
    LogoutRequest,
    PushTokenRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    TokenResponse,
    UserUpdateRequest,
    UserWithProfileResponse,
)
from app.services.email_service import (
    create_email_verification_token,
    decode_email_verification_token,
    send_verification_email,
)
from app.utils.rate_limit import AUTH_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_RATE_LIMIT)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user (buyer or mechanic). Admin registration is not allowed."""
    if body.role.value == "admin":
        raise HTTPException(status_code=403, detail="Admin registration not allowed")

    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Use a savepoint (begin_nested) so that user creation and profile creation
    # are atomic. If the profile flush fails mid-registration, the savepoint is
    # rolled back and the orphaned user row is discarded together with it.
    async with db.begin_nested():
        user = User(
            email=body.email,
            password_hash=hash_password(body.password),
            role=UserRole(body.role.value),
            first_name=body.first_name,
            last_name=body.last_name,
            phone=body.phone,
            is_verified=False,
        )
        db.add(user)
        await db.flush()

        if body.role.value == "mechanic":
            # Validate referral code if provided
            referred_by_code = None
            if body.referral_code:
                ref_result = await db.execute(
                    select(ReferralCode).where(ReferralCode.code == body.referral_code)
                )
                referral = ref_result.scalar_one_or_none()
                if not referral:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid referral code",
                    )
                referred_by_code = body.referral_code

            profile = MechanicProfile(
                user_id=user.id,
                city="",
                city_lat=0.0,
                city_lng=0.0,
                accepted_vehicle_types=["car"],
                is_active=False,  # Inactive until profile is completed
                referred_by=referred_by_code,
            )
            db.add(profile)
            await db.flush()

            # Increment uses_count on referral code
            if referred_by_code:
                referral.uses_count += 1
                await db.flush()

    # Send verification email
    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token)

    logger.info("user_registered", user_id=str(user.id), role=body.role.value)

    user_id_str = str(user.id)
    return TokenResponse(
        access_token=create_access_token(user_id_str),
        refresh_token=create_refresh_token(user_id_str),
    )


@router.post("/verify-email")
@limiter.limit(AUTH_RATE_LIMIT)
async def verify_email(request: Request, body: EmailVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify a user's email address using a JWT verification token."""
    email = decode_email_verification_token(body.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.is_verified:
        return {"status": "already_verified"}

    user.is_verified = True
    await db.flush()

    logger.info("email_verified", user_id=str(user.id), email=email)
    return {"status": "verified"}


@router.post("/resend-verification")
@limiter.limit(AUTH_RATE_LIMIT)
async def resend_verification(request: Request, body: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    """Resend the email verification link."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if not user or user.is_verified:
        return {"status": "sent"}

    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token)

    logger.info("verification_email_resent", user_id=str(user.id), email=body.email)
    return {"status": "sent"}


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return a JWT token pair."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    logger.info("user_login", user_id=str(user.id))
    user_id_str = str(user.id)
    return TokenResponse(
        access_token=create_access_token(user_id_str),
        refresh_token=create_refresh_token(user_id_str),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def refresh_tokens(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh token pair.

    SEC-008: The old refresh token is not explicitly invalidated because we use
    stateless JWTs. True revocation requires a token blacklist backed by Redis,
    which is planned as a future improvement. Until then, risk is mitigated by:
      - Short refresh token expiry (7 days)
      - A ``jti`` (JWT ID) claim on every token, enabling blacklisting later
      - Rate limiting on this endpoint
    """
    user_id = decode_refresh_token(body.refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # SEC-002: Check if the refresh token's jti has been blacklisted
    try:
        refresh_payload = jwt.decode(
            body.refresh_token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        jti = refresh_payload.get("jti")
        if jti:
            blacklisted = await db.execute(
                select(BlacklistedToken).where(BlacklistedToken.jti == jti)
            )
            if blacklisted.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token révoqué",
                )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Verify user still exists
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    logger.info("token_refreshed", user_id=user_id)
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserWithProfileResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def get_me(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated user's profile with mechanic profile if applicable."""
    # Re-fetch user with mechanic_profile eagerly loaded (since User.mechanic_profile uses lazy="raise")
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.mechanic_profile))
    )
    return result.scalar_one()


@router.patch("/me", response_model=UserWithProfileResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def update_me(
    request: Request,
    body: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's personal information."""
    # SEC-004: Only allow updating specific fields to prevent arbitrary attribute setting
    UPDATABLE_FIELDS = {"email", "first_name", "last_name", "phone"}
    update_data = body.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"] != user.email:
        result = await db.execute(select(User).where(User.email == update_data["email"]))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")

    for field, value in update_data.items():
        if field not in UPDATABLE_FIELDS:
            continue
        setattr(user, field, value)

    await db.flush()

    # Re-fetch with mechanic_profile loaded
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.mechanic_profile))
    )
    updated_user = result.scalar_one()
    return updated_user


@router.post("/push-token")
@limiter.limit(AUTH_RATE_LIMIT)
async def register_push_token(
    request: Request,
    body: PushTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or update the user's Expo push notification token."""
    user.expo_push_token = body.token
    # H-05: Use flush instead of commit -- the session middleware handles the commit
    await db.flush()
    return {"status": "ok"}


security = HTTPBearer()


@router.post("/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    body: LogoutRequest = LogoutRequest(),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Logout by blacklisting the current access token's jti and optionally the refresh token."""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token does not contain a jti claim",
        )

    # Check if already blacklisted
    existing = await db.execute(
        select(BlacklistedToken).where(BlacklistedToken.jti == jti)
    )
    if existing.scalar_one_or_none():
        return {"status": "already_logged_out"}

    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc)

    blacklisted = BlacklistedToken(
        jti=jti,
        expires_at=expires_at,
    )
    db.add(blacklisted)
    await db.flush()

    # Blacklist refresh token if provided
    if body.refresh_token:
        try:
            refresh_payload = jwt.decode(
                body.refresh_token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                issuer="emecano",
                options={"verify_iss": True},
            )
            refresh_jti = refresh_payload.get("jti")
            if refresh_jti:
                # Check if refresh token already blacklisted
                existing_refresh = await db.execute(
                    select(BlacklistedToken).where(BlacklistedToken.jti == refresh_jti)
                )
                if not existing_refresh.scalar_one_or_none():
                    refresh_exp = refresh_payload.get("exp")
                    refresh_expires_at = (
                        datetime.fromtimestamp(refresh_exp, tz=timezone.utc)
                        if refresh_exp
                        else datetime.now(timezone.utc)
                    )
                    blacklisted_refresh = BlacklistedToken(
                        jti=refresh_jti,
                        expires_at=refresh_expires_at,
                    )
                    db.add(blacklisted_refresh)
                    await db.flush()
                    logger.info("refresh_token_blacklisted", jti=refresh_jti)
        except JWTError:
            # Invalid refresh token -- just log and continue, access token is already blacklisted
            logger.warning("invalid_refresh_token_on_logout")

    logger.info("user_logged_out", jti=jti)
    return {"status": "logged_out"}
