import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.service import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_password_reset_token,
    decode_refresh_token,
    hash_password_async,
    verify_password_async,
)
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, security
from app.models.availability import Availability
from app.models.blacklisted_token import BlacklistedToken
from app.models.booking import Booking
from app.models.diploma import Diploma
from app.models.enums import BookingStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.message import Message
from app.models.notification import Notification
from app.models.referral import ReferralCode
from app.models.review import Review
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    EmailVerifyRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PushTokenRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserUpdateRequest,
    UserWithProfileResponse,
)
from app.services.email_service import (
    create_email_verification_token,
    decode_email_verification_token,
    generate_verification_code,
    send_password_reset_email,
    send_verification_email,
)
from app.services.storage import upload_file
from app.services.stripe_service import cancel_payment_intent
from app.utils.rate_limit import AUTH_RATE_LIMIT, limiter

# H-01: Dummy hash for constant-time login failure (prevents timing oracle)
_DUMMY_HASH = "$2b$12$LJ3m4ys3Lg2UxMHFSKDcOedTqJtFHSfVLO7GRFXlI0Xp9jHQvaFYe"

logger = structlog.get_logger()
router = APIRouter()

# SEC-004 / AUD-002: Per-email login attempt tracking for account lockout.
# Primary: Redis INCR + EXPIRE on key "login_attempts:{email}" (shared across workers).
# Fallback: In-memory dict when Redis is not available (dev/test).
_LOGIN_ATTEMPTS: dict[str, list[datetime]] = defaultdict(list)
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60  # 15 minutes
_MAX_LOGIN_ATTEMPTS_ENTRIES = 10000  # Max tracked emails to prevent memory leak

# ---------------------------------------------------------------------------
# Redis-backed login lockout helpers (AUD-002)
# ---------------------------------------------------------------------------
_redis_client = None
_redis_retry_after: float = 0  # monotonic timestamp; retry Redis after this time


async def _get_redis_client():
    """Return a shared async Redis client, or None if Redis is unavailable."""
    global _redis_client, _redis_retry_after
    if time.monotonic() < _redis_retry_after:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        _redis_retry_after = time.monotonic() + 60  # retry after 60 seconds
        logger.debug("redis_unavailable_for_login_lockout", redis_url="[redacted]")
        return None


def _lockout_redis_key(email: str) -> str:
    return f"login_attempts:{email}"


async def _check_login_lockout(email: str) -> bool:
    """Return True if the email is currently locked out.

    Uses Redis when available, falls back to the in-memory dict.
    """
    r = await _get_redis_client()
    if r is not None:
        try:
            count = await r.get(_lockout_redis_key(email))
            return count is not None and int(count) >= _MAX_LOGIN_ATTEMPTS
        except Exception:
            pass  # fall through to in-memory

    # Fallback: in-memory
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=_LOGIN_LOCKOUT_WINDOW_SECONDS)
    _cleanup_login_attempts_dict(cutoff)
    attempts = _LOGIN_ATTEMPTS.get(email, [])
    _LOGIN_ATTEMPTS[email] = [t for t in attempts if t > cutoff]
    return len(_LOGIN_ATTEMPTS[email]) >= _MAX_LOGIN_ATTEMPTS


async def _record_login_attempt(email: str) -> None:
    """Increment the failed-login counter for *email*.

    Uses Redis INCR + EXPIRE when available, falls back to in-memory dict.
    """
    r = await _get_redis_client()
    if r is not None:
        try:
            key = _lockout_redis_key(email)
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, _LOGIN_LOCKOUT_WINDOW_SECONDS)
            await pipe.execute()
            return
        except Exception:
            pass  # fall through to in-memory

    # Fallback: in-memory
    _LOGIN_ATTEMPTS[email].append(datetime.now(timezone.utc))


async def _clear_login_attempts(email: str) -> None:
    """Reset the counter on successful login.

    Deletes the Redis key when available, falls back to in-memory dict.
    """
    r = await _get_redis_client()
    if r is not None:
        try:
            await r.delete(_lockout_redis_key(email))
        except Exception:
            pass  # fall through to in-memory

    # Always clean in-memory as well (harmless no-op if empty)
    _LOGIN_ATTEMPTS.pop(email, None)


def _cleanup_login_attempts_dict(cutoff: datetime) -> None:
    """Prune stale entries and enforce max dict size (in-memory fallback only)."""
    stale_keys = [k for k, v in _LOGIN_ATTEMPTS.items() if all(t <= cutoff for t in v)]
    for k in stale_keys:
        del _LOGIN_ATTEMPTS[k]
    if len(_LOGIN_ATTEMPTS) > _MAX_LOGIN_ATTEMPTS_ENTRIES:
        sorted_keys = sorted(
            _LOGIN_ATTEMPTS.keys(),
            key=lambda k: max(_LOGIN_ATTEMPTS[k]) if _LOGIN_ATTEMPTS[k] else datetime.min.replace(tzinfo=timezone.utc),
        )
        for k in sorted_keys[: len(_LOGIN_ATTEMPTS) - _MAX_LOGIN_ATTEMPTS_ENTRIES]:
            del _LOGIN_ATTEMPTS[k]


def _sanitize_csv_cell(value: str | None) -> str | None:
    """Sanitize a string value to prevent CSV/Excel formula injection.

    If the value starts with a character that Excel or other spreadsheet
    applications interpret as a formula prefix, prepend a single quote to
    neutralize it.
    """
    if value is None:
        return None
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(AUTH_RATE_LIMIT)
async def register(request: Request, response: Response, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user (buyer or mechanic). Admin registration is not allowed."""
    # L-2: Prevent caching of token responses by edge proxies/CDNs
    response.headers["Cache-Control"] = "no-store"
    if body.role.value == "admin":
        raise HTTPException(status_code=403, detail="Admin registration not allowed")

    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        # H-02: Don't reveal email existence - return same response as success
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"message": "Verification email sent. Check your inbox."},
        )

    # Use a savepoint (begin_nested) so that user creation and profile creation
    # are atomic. If the profile flush fails mid-registration, the savepoint is
    # rolled back and the orphaned user row is discarded together with it.
    try:
        async with db.begin_nested():
            user = User(
                email=body.email,
                password_hash=await hash_password_async(body.password),
                role=UserRole(body.role.value),
                first_name=body.first_name,
                last_name=body.last_name,
                phone=body.phone,
                is_verified=False,
                is_active=True,
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
                    city_lat=None,
                    city_lng=None,
                    accepted_vehicle_types=["car"],
                    is_active=False,  # Inactive until profile is completed
                    referred_by=referred_by_code,
                )
                db.add(profile)
                await db.flush()

                # AUD-H04: Increment uses_count atomically to prevent race conditions
                if referred_by_code:
                    await db.execute(
                        update(ReferralCode)
                        .where(ReferralCode.id == referral.id)
                        .values(uses_count=ReferralCode.uses_count + 1)
                    )
                    await db.flush()
    except IntegrityError:
        await db.rollback()
        # M-010: Race condition — email was taken between our check and insert.
        # Return anti-enumeration response (same as duplicate email above).
        logger.info("registration_race_condition")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"message": "Verification email sent. Check your inbox."},
        )

    # CRIT-5: Generate OTP code and store on user for verification
    code = generate_verification_code()
    user.verification_code = code
    user.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.flush()

    # Send verification email with OTP code
    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token, code=code)

    # PERF-09: Increment Prometheus registration counter
    from app.metrics import USERS_REGISTERED
    USERS_REGISTERED.labels(role=body.role.value).inc()

    logger.info("user_registered", user_id=str(user.id), role=body.role.value)

    # AUDIT-9: Do NOT return JWT at registration — require email verification first.
    # Returning tokens here would give full API access before the user verifies
    # their email, bypassing is_verified checks on sensitive endpoints.
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"message": "Verification email sent. Check your inbox."},
    )


@router.post("/verify-email")
@limiter.limit(AUTH_RATE_LIMIT)
async def verify_email(request: Request, body: EmailVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify a user's email address using a JWT token or OTP code."""

    # CRIT-5: OTP code flow (mobile app)
    if body.code and body.email:
        result = await db.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code",
            )

        if user.is_verified:
            return {"status": "already_verified"}

        # Validate code and expiry
        if (
            not user.verification_code
            or not user.verification_code_expires_at
            or user.verification_code != body.code
            or user.verification_code_expires_at < datetime.now(timezone.utc)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code",
            )

        user.is_verified = True
        user.verification_code = None
        user.verification_code_expires_at = None
        await db.flush()

        logger.info("email_verified_otp", user_id=str(user.id))
        return {"status": "verified"}

    # JWT token flow (web link fallback)
    if body.token:
        from app.services.email_service import decode_email_verification_token_full

        token_payload = decode_email_verification_token_full(body.token)
        if not token_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )
        email = token_payload["sub"]
        verify_jti = token_payload.get("jti")

        # R-003: Check if the verification token has already been used
        if verify_jti:
            blacklisted = await db.execute(
                select(BlacklistedToken).where(BlacklistedToken.jti == verify_jti)
            )
            if blacklisted.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This verification token has already been used",
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
        user.verification_code = None
        user.verification_code_expires_at = None
        await db.flush()

        # R-003: Blacklist the verification token to prevent reuse
        if verify_jti:
            verify_exp = token_payload.get("exp")
            verify_expires_at = (
                datetime.fromtimestamp(verify_exp, tz=timezone.utc)
                if verify_exp
                else datetime.now(timezone.utc)
            )
            db.add(BlacklistedToken(jti=verify_jti, expires_at=verify_expires_at))
            await db.flush()

        logger.info("email_verified", user_id=str(user.id))
        return {"status": "verified"}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Either 'token' or both 'code' and 'email' are required",
    )


@router.post("/resend-verification")
@limiter.limit(AUTH_RATE_LIMIT)
async def resend_verification(request: Request, body: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    """Resend the email verification link."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if not user or user.is_verified:
        return {"status": "sent"}

    # CRIT-5: Regenerate OTP code on resend
    code = generate_verification_code()
    user.verification_code = code
    user.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.flush()

    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token, code=code)

    logger.info("verification_email_resent", user_id=str(user.id))
    return {"status": "sent"}


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(request: Request, response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return a JWT token pair."""
    # L-2: Prevent caching of token responses by edge proxies/CDNs
    response.headers["Cache-Control"] = "no-store"
    # SEC-004 / AUD-002: Per-email lockout after N failed attempts (Redis-backed)
    if await _check_login_lockout(body.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user:
        # H-01: Hash against dummy to prevent timing-based email enumeration
        await verify_password_async(body.password, _DUMMY_HASH)
        await _record_login_attempt(body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not await verify_password_async(body.password, user.password_hash):
        # SEC-004: Record failed attempt (Redis or in-memory fallback)
        await _record_login_attempt(body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # SEC-004: Reset counter on successful login
    await _clear_login_attempts(body.email)

    logger.info("user_login", user_id=str(user.id))
    user_id_str = str(user.id)
    return TokenResponse(
        access_token=create_access_token(user_id_str),
        refresh_token=create_refresh_token(user_id_str),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def refresh_tokens(request: Request, response: Response, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh token pair.

    SEC-008: The old refresh token is blacklisted (via its ``jti``) during
    rotation (see AUD-014 below). This prevents reuse of the old token after
    a new pair has been issued.
    """
    # L-2: Prevent caching of token responses by edge proxies/CDNs
    response.headers["Cache-Control"] = "no-store"
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
                    detail="Token revoked",
                )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # AUD-014: Blacklist the old refresh token JTI on rotation
    old_jti = refresh_payload.get("jti")
    if old_jti:
        old_exp = refresh_payload.get("exp")
        old_expires_at = (
            datetime.fromtimestamp(old_exp, tz=timezone.utc)
            if old_exp
            else datetime.now(timezone.utc)
        )
        db.add(BlacklistedToken(jti=old_jti, expires_at=old_expires_at))
        await db.flush()

    # Verify user still exists
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # SEC-04: Reject refresh tokens issued before a password change
    if user.password_changed_at:
        refresh_iat = refresh_payload.get("iat")
        if refresh_iat:
            issued_at = datetime.fromtimestamp(refresh_iat, tz=timezone.utc)
            if issued_at < user.password_changed_at:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token invalidated by password change",
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

    email_changed = False
    if "email" in update_data and update_data["email"] != user.email:
        result = await db.execute(select(User).where(User.email == update_data["email"]))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")
        email_changed = True

    for field, value in update_data.items():
        if field not in UPDATABLE_FIELDS:
            continue
        setattr(user, field, value)

    # SEC-006: If email changed, require re-verification
    if email_changed:
        user.is_verified = False
        verification_token = create_email_verification_token(user.email)
        await send_verification_email(user.email, verification_token)

    await db.flush()

    # Re-fetch with mechanic_profile loaded
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.mechanic_profile))
    )
    updated_user = result.scalar_one()
    return updated_user


@router.post("/me/photo", status_code=status.HTTP_200_OK)
@limiter.limit(AUTH_RATE_LIMIT)
async def upload_user_photo(
    request: Request,
    photo: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload or replace the user's profile photo."""
    try:
        photo_url = await upload_file(photo, "avatars")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    user.photo_url = photo_url
    await db.flush()
    logger.info("user_photo_uploaded", user_id=str(user.id))
    return {"photo_url": photo_url}


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


@router.delete("/push-token")
@limiter.limit(AUTH_RATE_LIMIT)
async def unregister_push_token(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """HIGH-02: Remove the user's push token on logout to stop notifications."""
    user.expo_push_token = None
    await db.flush()
    return {"status": "ok"}


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
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    # SEC-003: Only allow access tokens to be used for logout
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only access tokens can be used for logout",
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
        except jwt.PyJWTError:
            # Invalid refresh token -- just log and continue, access token is already blacklisted
            logger.warning("invalid_refresh_token_on_logout")

    logger.info("user_logged_out", jti=jti)
    return {"status": "logged_out"}


# ---------------------------------------------------------------------------
# Password Reset Flow
# ---------------------------------------------------------------------------


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link. Always returns success to prevent email enumeration."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        reset_token = create_password_reset_token(str(user.id))
        await send_password_reset_email(user.email, reset_token)
        logger.info("password_reset_requested", user_id=str(user.id))

    return MessageResponse(
        message="If an account exists with this email, a password reset link has been sent"
    )


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password using a valid password reset token."""
    payload = decode_password_reset_token(body.token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    # I-004: Reject tokens that lack a jti claim to prevent blacklist bypass
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token",
        )

    # SEC-002: Blacklist the token FIRST to prevent TOCTOU race condition.
    # BlacklistedToken.jti has a UNIQUE constraint, so concurrent requests
    # with the same token will fail with IntegrityError on the second insert.
    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc)
    try:
        db.add(BlacklistedToken(jti=jti, expires_at=expires_at))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This token has already been used",
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Update password (token already consumed, safe from replay)
    user.password_hash = await hash_password_async(body.new_password)
    # SEC-005: Mark password change time to invalidate all pre-existing tokens
    user.password_changed_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info("password_reset_completed", user_id=user_id)
    return MessageResponse(message="Password reset successfully")


@router.post("/change-password", response_model=MessageResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password (requires authentication)."""
    if not await verify_password_async(body.old_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect old password",
        )

    # AUD-H08: Ensure new password is different from old password
    if await verify_password_async(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from old password",
        )

    user.password_hash = await hash_password_async(body.new_password)
    # SEC-005: Mark password change time to invalidate all pre-existing tokens
    user.password_changed_at = datetime.now(timezone.utc)
    await db.flush()

    # AUD-H08: Blacklist the current token. password_changed_at (set above)
    # invalidates ALL older tokens at verification time, so every active
    # session is effectively revoked — not just this one.
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True, "verify_exp": False},
        )
        jti = payload.get("jti")
        if jti:
            exp = payload.get("exp")
            expires_at = (
                datetime.fromtimestamp(exp, tz=timezone.utc)
                if exp
                else datetime.now(timezone.utc)
            )
            db.add(BlacklistedToken(jti=jti, expires_at=expires_at))
            await db.flush()
    except jwt.PyJWTError:
        pass  # Token already validated by get_current_user

    logger.info("password_changed", user_id=str(user.id))
    return MessageResponse(message="Password changed successfully")


# ---------------------------------------------------------------------------
# GDPR: Account Deletion (Article 17) & Data Export (Article 20)
# ---------------------------------------------------------------------------


@router.delete("/me", response_model=MessageResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def delete_account(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete (anonymize) the current user's account per GDPR Article 17."""
    # SEC-004: Prevent the last admin from deleting their own account
    if user.role == UserRole.ADMIN:
        admin_count = await db.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        if admin_count.scalar() <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the last admin account. Promote another user to admin first.",
            )

    # BUG-007: Check for active bookings before allowing account deletion
    # AUDIT-FIX6: Include VALIDATED to prevent deletion while payment is held
    active_statuses = [
        BookingStatus.CONFIRMED,
        BookingStatus.AWAITING_MECHANIC_CODE,
        BookingStatus.CHECK_IN_DONE,
        BookingStatus.CHECK_OUT_DONE,
        BookingStatus.VALIDATED,
    ]
    active_as_buyer = await db.execute(
        select(Booking).where(
            Booking.buyer_id == user.id,
            Booking.status.in_(active_statuses),
        )
    )
    if active_as_buyer.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have active bookings. Please complete or cancel them before deleting your account.",
        )

    # Also check as mechanic
    if user.role == UserRole.MECHANIC:
        profile_check = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        mech_profile = profile_check.scalar_one_or_none()
        if mech_profile:
            active_as_mechanic = await db.execute(
                select(Booking).where(
                    Booking.mechanic_id == mech_profile.id,
                    Booking.status.in_(active_statuses),
                )
            )
            if active_as_mechanic.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You have active bookings. Please complete or cancel them before deleting your account.",
                )

    # 1. Cancel pending bookings (as buyer)
    pending_bookings_result = await db.execute(
        select(Booking).where(
            Booking.buyer_id == user.id,
            Booking.status == BookingStatus.PENDING_ACCEPTANCE,
        )
    )
    pending_bookings = pending_bookings_result.scalars().all()
    for booking in pending_bookings:
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancelled_by = "buyer"
        if booking.stripe_payment_intent_id:
            try:
                await cancel_payment_intent(booking.stripe_payment_intent_id)
            except Exception:
                logger.warning(
                    "stripe_cancel_failed_on_account_deletion",
                    booking_id=str(booking.id),
                )
    await db.flush()

    # 2. If mechanic: deactivate profile and clean up personal documents (RGPD Article 17)
    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            profile.is_active = False
            # GDPR-R01: Close Stripe Connect account (best-effort)
            if profile.stripe_account_id:
                try:
                    import stripe as _stripe
                    if settings.STRIPE_SECRET_KEY and not profile.stripe_account_id.startswith("acct_mock_"):
                        await asyncio.to_thread(
                            _stripe.Account.delete,
                            profile.stripe_account_id,
                            api_key=settings.STRIPE_SECRET_KEY,
                        )
                    logger.info("stripe_connect_account_closed", account_id=profile.stripe_account_id)
                except Exception:
                    logger.exception("stripe_connect_account_close_failed", account_id=profile.stripe_account_id)
                profile.stripe_account_id = None
            # AUD-012: Clear personal documents (RGPD Article 17)
            profile.identity_document_url = None
            profile.selfie_with_id_url = None
            profile.cv_url = None
            profile.photo_url = None
            # Delete diplomas
            await db.execute(delete(Diploma).where(Diploma.mechanic_id == profile.id))
            # Delete availabilities
            await db.execute(delete(Availability).where(Availability.mechanic_id == profile.id))
            await db.flush()
            # Also cancel pending bookings where this mechanic is assigned
            mech_pending_result = await db.execute(
                select(Booking).where(
                    Booking.mechanic_id == profile.id,
                    Booking.status == BookingStatus.PENDING_ACCEPTANCE,
                )
            )
            for booking in mech_pending_result.scalars().all():
                booking.status = BookingStatus.CANCELLED
                booking.cancelled_at = datetime.now(timezone.utc)
                booking.cancelled_by = "mechanic"
                if booking.stripe_payment_intent_id:
                    try:
                        await cancel_payment_intent(booking.stripe_payment_intent_id)
                    except Exception:
                        logger.warning(
                            "stripe_cancel_failed_on_account_deletion",
                            booking_id=str(booking.id),
                        )
            await db.flush()

    # 3. FIX-9: Anonymize sent messages instead of deleting (GDPR Article 17)
    # Preserves conversation history for the other party while removing PII
    await db.execute(
        update(Message)
        .where(Message.sender_id == user.id)
        .values(content="[Message supprime]", sender_id=None)
    )
    await db.flush()

    # 4. Delete notifications
    await db.execute(
        delete(Notification).where(Notification.user_id == user.id)
    )
    await db.flush()

    # 5. Anonymize reviews (RGPD Article 17)
    reviews_result = await db.execute(
        select(Review).where(
            (Review.reviewer_id == user.id) | (Review.reviewee_id == user.id)
        )
    )
    for review in reviews_result.scalars().all():
        if review.reviewer_id == user.id:
            review.comment = None
        # Keep rating and reviewee_id for aggregate stats
    await db.flush()

    # 6. Anonymize user data
    anon_uuid = str(uuid.uuid4())
    user.email = f"deleted_{anon_uuid}@deleted.emecano.local"
    user.first_name = "Utilisateur"
    user.last_name = "Supprime"
    user.phone = None
    user.password_hash = await hash_password_async(str(uuid.uuid4()))
    user.expo_push_token = None
    await db.flush()

    # 7. Blacklist current access token
    token = credentials.credentials
    try:
        token_payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        jti = token_payload.get("jti")
        if jti:
            existing = await db.execute(
                select(BlacklistedToken).where(BlacklistedToken.jti == jti)
            )
            if not existing.scalar_one_or_none():
                exp = token_payload.get("exp")
                expires_at = (
                    datetime.fromtimestamp(exp, tz=timezone.utc)
                    if exp
                    else datetime.now(timezone.utc)
                )
                db.add(BlacklistedToken(jti=jti, expires_at=expires_at))
                await db.flush()
    except jwt.PyJWTError:
        pass  # Token is already valid since get_current_user succeeded

    logger.info("account_deleted", user_id=str(user.id))
    return MessageResponse(message="Your account has been deleted")


@router.get("/me/export")
@limiter.limit(AUTH_RATE_LIMIT)
async def export_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user personal data per GDPR Article 20.

    SEC: All user-facing string fields are sanitized to prevent CSV/Excel
    formula injection when the exported JSON is converted to a spreadsheet.
    """
    # Profile info
    profile_data = {
        "id": str(user.id),
        "email": _sanitize_csv_cell(user.email),
        "first_name": _sanitize_csv_cell(user.first_name),
        "last_name": _sanitize_csv_cell(user.last_name),
        "phone": _sanitize_csv_cell(user.phone),
        "role": user.role.value if isinstance(user.role, UserRole) else user.role,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

    # Bookings (as buyer)
    bookings_result = await db.execute(
        select(Booking).where(Booking.buyer_id == user.id)
    )
    bookings = [
        {
            "id": str(b.id),
            "status": b.status.value if isinstance(b.status, BookingStatus) else b.status,
            "vehicle_type": b.vehicle_type.value if hasattr(b.vehicle_type, "value") else b.vehicle_type,
            "vehicle_brand": _sanitize_csv_cell(b.vehicle_brand),
            "vehicle_model": _sanitize_csv_cell(b.vehicle_model),
            "vehicle_year": b.vehicle_year,
            "total_price": str(b.total_price),
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in bookings_result.scalars().all()
    ]

    # Reviews written
    reviews_result = await db.execute(
        select(Review).where(Review.reviewer_id == user.id)
    )
    reviews = [
        {
            "id": str(r.id),
            "booking_id": str(r.booking_id),
            "rating": r.rating,
            "comment": _sanitize_csv_cell(r.comment),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reviews_result.scalars().all()
    ]

    # Messages sent
    messages_result = await db.execute(
        select(Message).where(Message.sender_id == user.id)
    )
    messages = [
        {
            "id": str(m.id),
            "booking_id": str(m.booking_id),
            "content": _sanitize_csv_cell(m.content),
            "is_template": m.is_template,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages_result.scalars().all()
    ]

    # Notifications
    notifications_result = await db.execute(
        select(Notification).where(Notification.user_id == user.id)
    )
    notifications = [
        {
            "id": str(n.id),
            "type": _sanitize_csv_cell(n.type),
            "title": _sanitize_csv_cell(n.title),
            "body": _sanitize_csv_cell(n.body),
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications_result.scalars().all()
    ]

    export = {
        "profile": profile_data,
        "bookings": bookings,
        "reviews": reviews,
        "messages": messages,
        "notifications": notifications,
    }

    # If mechanic: include profile data, availability, diplomas
    if user.role == UserRole.MECHANIC or (isinstance(user.role, str) and user.role == "mechanic"):
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        mechanic_profile = profile_result.scalar_one_or_none()
        if mechanic_profile:
            export["mechanic_profile"] = {
                "id": str(mechanic_profile.id),
                "city": _sanitize_csv_cell(mechanic_profile.city),
                "city_lat": float(mechanic_profile.city_lat) if mechanic_profile.city_lat is not None else None,
                "city_lng": float(mechanic_profile.city_lng) if mechanic_profile.city_lng is not None else None,
                "max_radius_km": mechanic_profile.max_radius_km,
                "free_zone_km": mechanic_profile.free_zone_km,
                "accepted_vehicle_types": mechanic_profile.accepted_vehicle_types,
                "rating_avg": float(mechanic_profile.rating_avg),
                "total_reviews": mechanic_profile.total_reviews,
                "is_active": mechanic_profile.is_active,
            }

            # Availability
            avail_result = await db.execute(
                select(Availability).where(Availability.mechanic_id == mechanic_profile.id)
            )
            export["availability"] = [
                {
                    "id": str(a.id),
                    "date": a.date.isoformat() if a.date else None,
                    "start_time": a.start_time.isoformat() if a.start_time else None,
                    "end_time": a.end_time.isoformat() if a.end_time else None,
                    "is_booked": a.is_booked,
                }
                for a in avail_result.scalars().all()
            ]

            # Diplomas
            diplomas_result = await db.execute(
                select(Diploma).where(Diploma.mechanic_id == mechanic_profile.id)
            )
            export["diplomas"] = [
                {
                    "id": str(d.id),
                    "name": _sanitize_csv_cell(d.name),
                    "year": d.year,
                }
                for d in diplomas_result.scalars().all()
            ]

    return export
