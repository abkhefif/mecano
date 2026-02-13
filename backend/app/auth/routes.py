import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.service import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_password_reset_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
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
    send_password_reset_email,
    send_verification_email,
)
from app.services.stripe_service import cancel_payment_intent
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
        message="Si un compte existe avec cet email, un lien de reinitialisation a ete envoye"
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
            detail="Token de reinitialisation invalide ou expire",
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    # Check if the token has already been used (blacklisted)
    if jti:
        blacklisted = await db.execute(
            select(BlacklistedToken).where(BlacklistedToken.jti == jti)
        )
        if blacklisted.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce token a deja ete utilise",
            )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouve",
        )

    # Update password
    user.password_hash = hash_password(body.new_password)
    await db.flush()

    # Blacklist the reset token to prevent reuse
    if jti:
        exp = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc)
        blacklisted_token = BlacklistedToken(
            jti=jti,
            expires_at=expires_at,
        )
        db.add(blacklisted_token)
        await db.flush()

    logger.info("password_reset_completed", user_id=user_id)
    return MessageResponse(message="Mot de passe reinitialise avec succes")


@router.post("/change-password", response_model=MessageResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password (requires authentication)."""
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ancien mot de passe incorrect",
        )

    user.password_hash = hash_password(body.new_password)
    await db.flush()

    logger.info("password_changed", user_id=str(user.id))
    return MessageResponse(message="Mot de passe modifie avec succes")


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

    # 2. If mechanic: deactivate profile
    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            profile.is_active = False
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

    # 3. Delete messages
    await db.execute(
        delete(Message).where(Message.sender_id == user.id)
    )
    await db.flush()

    # 4. Delete notifications
    await db.execute(
        delete(Notification).where(Notification.user_id == user.id)
    )
    await db.flush()

    # 5. Anonymize user data
    anon_uuid = str(uuid.uuid4())
    user.email = f"deleted_{anon_uuid}@deleted.emecano.local"
    user.first_name = "Utilisateur"
    user.last_name = "supprime"
    user.phone = None
    user.password_hash = hash_password(str(uuid.uuid4()))
    user.expo_push_token = None
    await db.flush()

    # 6. Blacklist current access token
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
    except JWTError:
        pass  # Token is already valid since get_current_user succeeded

    logger.info("account_deleted", user_id=str(user.id))
    return MessageResponse(message="Votre compte a ete supprime")


@router.get("/me/export")
@limiter.limit(AUTH_RATE_LIMIT)
async def export_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user personal data per GDPR Article 20."""
    # Profile info
    profile_data = {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
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
            "vehicle_brand": b.vehicle_brand,
            "vehicle_model": b.vehicle_model,
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
            "comment": r.comment,
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
            "content": m.content,
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
            "type": n.type,
            "title": n.title,
            "body": n.body,
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
                "city": mechanic_profile.city,
                "city_lat": float(mechanic_profile.city_lat),
                "city_lng": float(mechanic_profile.city_lng),
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
                    "name": d.name,
                    "year": d.year,
                }
                for d in diplomas_result.scalars().all()
            ]

    return export
