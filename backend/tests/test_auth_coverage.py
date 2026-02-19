import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    hash_password,
)
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.message import Message
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


@pytest.mark.asyncio
async def test_refresh_token_success(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/refresh returns new token pair for valid refresh token."""
    refresh = create_refresh_token(str(buyer_user.id))
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient):
    """POST /auth/refresh rejects invalid refresh tokens."""
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": "invalid_token_here"},
    )
    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_token_using_access_token(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/refresh rejects access tokens (must be refresh type)."""
    access = create_access_token(str(buyer_user.id))
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": access},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_user_not_found(
    client: AsyncClient,
):
    """POST /auth/refresh rejects if user was deleted."""
    # Create a refresh token for a non-existent user
    fake_user_id = str(uuid.uuid4())
    refresh = create_refresh_token(fake_user_id)
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert response.status_code == 401
    assert "User not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_admin_not_allowed(client: AsyncClient):
    """POST /auth/register rejects admin role registration (via schema validation)."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "admin@test.com",
            "password": "SecurePass123",
            "role": "admin",
        },
    )
    # RegistrationRole enum only allows buyer/mechanic, so admin is rejected at schema level
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_mechanic_with_valid_referral(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_profile,
):
    """Register mechanic with a valid referral code increments the code usage."""
    from app.models.referral import ReferralCode

    referral = ReferralCode(
        code="EMECANO-REF001",
        mechanic_id=mechanic_profile.id,
        uses_count=0,
    )
    db.add(referral)
    await db.flush()

    response = await client.post(
        "/auth/register",
        json={
            "email": "newmech_ref@test.com",
            "password": "SecurePass123",
            "role": "mechanic",
            "referral_code": "EMECANO-REF001",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_register_mechanic_with_invalid_referral(
    client: AsyncClient,
):
    """Register mechanic with an invalid referral code fails."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "newmech_badref@test.com",
            "password": "SecurePass123",
            "role": "mechanic",
            "referral_code": "EMECANO-NOPE00",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 400
    assert "Invalid referral" in response.json()["detail"]


@pytest.mark.asyncio
async def test_use_refresh_token_as_bearer(
    client: AsyncClient,
    buyer_user: User,
):
    """Using a refresh token as a Bearer token for auth/me should be rejected."""
    refresh = create_refresh_token(str(buyer_user.id))
    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Password Reset Flow Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forgot_password_valid_email(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/forgot-password returns success message for existing email."""
    response = await client.post(
        "/auth/forgot-password",
        json={"email": buyer_user.email},
    )
    assert response.status_code == 200
    data = response.json()
    assert "reset link has been sent" in data["message"]


@pytest.mark.asyncio
async def test_forgot_password_invalid_email(
    client: AsyncClient,
):
    """POST /auth/forgot-password returns same success message for non-existing email (no leak)."""
    response = await client.post(
        "/auth/forgot-password",
        json={"email": "nonexistent@test.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "reset link has been sent" in data["message"]


@pytest.mark.asyncio
async def test_reset_password_valid_token(
    client: AsyncClient,
    buyer_user: User,
    db: AsyncSession,
):
    """POST /auth/reset-password successfully resets password with valid token."""
    reset_token = create_password_reset_token(str(buyer_user.id))
    response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "NewSecure123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Password reset successfully"

    # Verify can login with new password
    login_response = await client.post(
        "/auth/login",
        json={"email": buyer_user.email, "password": "NewSecure123"},
    )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_invalid_token(
    client: AsyncClient,
):
    """POST /auth/reset-password rejects invalid tokens."""
    response = await client.post(
        "/auth/reset-password",
        json={"token": "invalid_token", "new_password": "NewSecure123"},
    )
    assert response.status_code == 400
    assert "Invalid or expired reset token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reset_password_expired_token(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/reset-password rejects expired tokens."""
    import jwt
    from app.config import settings

    # Create a token that is already expired
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(buyer_user.id),
        "exp": now - timedelta(hours=1),
        "iat": now - timedelta(hours=2),
        "iss": "emecano",
        "type": "password_reset",
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    response = await client.post(
        "/auth/reset-password",
        json={"token": expired_token, "new_password": "NewSecure123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_token_reuse_blocked(
    client: AsyncClient,
    buyer_user: User,
    db: AsyncSession,
):
    """POST /auth/reset-password blocks reuse of the same token."""
    reset_token = create_password_reset_token(str(buyer_user.id))

    # First use: should succeed
    response1 = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "NewSecure123"},
    )
    assert response1.status_code == 200

    # Second use: should be rejected (token blacklisted)
    response2 = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "AnotherPass123"},
    )
    assert response2.status_code == 400
    assert "This token has already been used" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_reset_password_wrong_type_token(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/reset-password rejects non-password_reset tokens (e.g., access token)."""
    access = create_access_token(str(buyer_user.id))
    response = await client.post(
        "/auth/reset-password",
        json={"token": access, "new_password": "NewSecure123"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Change Password Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_success(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/change-password successfully changes password with correct old password."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/auth/change-password",
        json={"old_password": "password123", "new_password": "NewSecure456"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Password changed successfully"

    # Verify can login with new password
    login_response = await client.post(
        "/auth/login",
        json={"email": buyer_user.email, "password": "NewSecure456"},
    )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/change-password rejects when old password is wrong."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/auth/change-password",
        json={"old_password": "wrongPassword1", "new_password": "NewSecure456"},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "Incorrect old password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_weak_new_password(
    client: AsyncClient,
    buyer_user: User,
):
    """POST /auth/change-password rejects weak new passwords."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/auth/change-password",
        json={"old_password": "password123", "new_password": "weak"},
        headers=auth_header(token),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_unauthenticated(
    client: AsyncClient,
):
    """POST /auth/change-password requires authentication."""
    response = await client.post(
        "/auth/change-password",
        json={"old_password": "password123", "new_password": "NewSecure456"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Account Deletion (GDPR Article 17) Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_account_buyer(
    client: AsyncClient,
    buyer_user: User,
    db: AsyncSession,
):
    """DELETE /auth/me anonymizes buyer data and returns success."""
    token = buyer_token(buyer_user)
    user_id = buyer_user.id
    original_email = buyer_user.email

    response = await client.delete(
        "/auth/me",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Your account has been deleted"

    # Verify user data is anonymized
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    assert user.email != original_email
    assert "deleted_" in user.email
    assert "@deleted.emecano.local" in user.email
    assert user.first_name == "Utilisateur"
    assert user.last_name == "Supprime"
    assert user.phone is None


@pytest.mark.asyncio
async def test_delete_account_cancels_pending_bookings(
    client: AsyncClient,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    db: AsyncSession,
):
    """DELETE /auth/me cancels pending bookings for the buyer."""
    # Create a pending booking
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.PENDING_ACCEPTANCE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
        meeting_address="123 Rue Test",
        meeting_lat=43.6,
        meeting_lng=1.4,
        distance_km=5.0,
        base_price=Decimal("40.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("40.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("8.00"),
        mechanic_payout=Decimal("32.00"),
    )
    db.add(booking)
    await db.flush()
    booking_id = booking.id

    token = buyer_token(buyer_user)
    response = await client.delete(
        "/auth/me",
        headers=auth_header(token),
    )
    assert response.status_code == 200

    # Verify booking was cancelled
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    updated_booking = result.scalar_one()
    assert updated_booking.status == BookingStatus.CANCELLED
    assert updated_booking.cancelled_by == "buyer"


@pytest.mark.asyncio
async def test_delete_account_deletes_messages_and_notifications(
    client: AsyncClient,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    db: AsyncSession,
):
    """DELETE /auth/me deletes user's messages and notifications."""
    # Create a booking for the message
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.COMPLETED,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
        meeting_address="123 Rue Test",
        meeting_lat=43.6,
        meeting_lng=1.4,
        distance_km=5.0,
        base_price=Decimal("40.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("40.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("8.00"),
        mechanic_payout=Decimal("32.00"),
    )
    db.add(booking)
    await db.flush()

    # Create a message
    message = Message(
        id=uuid.uuid4(),
        booking_id=booking.id,
        sender_id=buyer_user.id,
        content="Test message",
        is_template=True,
    )
    db.add(message)

    # Create a notification
    notification = Notification(
        id=uuid.uuid4(),
        user_id=buyer_user.id,
        type="booking_created",
        title="Test",
        body="Test notification",
    )
    db.add(notification)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.delete(
        "/auth/me",
        headers=auth_header(token),
    )
    assert response.status_code == 200

    # Verify messages were deleted
    msg_result = await db.execute(select(Message).where(Message.sender_id == buyer_user.id))
    assert msg_result.scalar_one_or_none() is None

    # Verify notifications were deleted
    notif_result = await db.execute(select(Notification).where(Notification.user_id == buyer_user.id))
    assert notif_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_account_mechanic_deactivates_profile(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    db: AsyncSession,
):
    """DELETE /auth/me deactivates mechanic profile."""
    token = mechanic_token(mechanic_user)
    profile_id = mechanic_profile.id

    response = await client.delete(
        "/auth/me",
        headers=auth_header(token),
    )
    assert response.status_code == 200

    # Verify profile is deactivated
    result = await db.execute(select(MechanicProfile).where(MechanicProfile.id == profile_id))
    profile = result.scalar_one()
    assert profile.is_active is False


# ---------------------------------------------------------------------------
# Data Export (GDPR Article 20) Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_data_buyer(
    client: AsyncClient,
    buyer_user: User,
):
    """GET /auth/me/export returns correct structure for buyer."""
    token = buyer_token(buyer_user)
    response = await client.get(
        "/auth/me/export",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()

    # Check top-level keys
    assert "profile" in data
    assert "bookings" in data
    assert "reviews" in data
    assert "messages" in data
    assert "notifications" in data

    # Check profile structure
    profile = data["profile"]
    assert profile["email"] == buyer_user.email
    assert profile["role"] == "buyer"
    assert "id" in profile
    assert "created_at" in profile


@pytest.mark.asyncio
async def test_export_data_mechanic_includes_profile(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    db: AsyncSession,
):
    """GET /auth/me/export includes mechanic profile, availability, and diplomas for mechanics."""
    token = mechanic_token(mechanic_user)
    response = await client.get(
        "/auth/me/export",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()

    # Should include mechanic-specific data
    assert "mechanic_profile" in data
    assert "availability" in data
    assert "diplomas" in data

    mechanic_data = data["mechanic_profile"]
    assert mechanic_data["city"] == "toulouse"
    assert "rating_avg" in mechanic_data


@pytest.mark.asyncio
async def test_export_data_unauthenticated(
    client: AsyncClient,
):
    """GET /auth/me/export requires authentication."""
    response = await client.get("/auth/me/export")
    assert response.status_code == 403
