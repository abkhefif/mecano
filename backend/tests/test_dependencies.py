import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.models.enums import UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


@pytest.mark.asyncio
async def test_get_current_user_valid_token(
    client: AsyncClient,
    buyer_user: User,
):
    """Test that a valid token returns the correct user."""
    token = buyer_token(buyer_user)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == "buyer@test.com"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(client: AsyncClient):
    """Test that an invalid JWT returns 401."""
    response = await client.get("/auth/me", headers=auth_header("not.a.valid.jwt"))
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_no_sub_in_token(
    client: AsyncClient,
    db: AsyncSession,
):
    """Test that a JWT with type=access but no 'sub' claim returns 401."""
    import jwt
    from app.config import settings

    # Create a token with type=access but without 'sub'
    token = jwt.encode({
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iss": "emecano",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_user_not_found(
    client: AsyncClient,
    db: AsyncSession,
):
    """Test that a valid JWT for a non-existent user returns 401."""
    token = create_access_token(str(uuid.uuid4()))
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "User not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_buyer_with_mechanic_token(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a mechanic cannot access a buyer-only endpoint."""
    token = mechanic_token(mechanic_user)
    # Try to create a booking (requires buyer role)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(uuid.uuid4()),
            "availability_id": str(uuid.uuid4()),
            "vehicle_type": "car",
            "vehicle_brand": "Test",
            "vehicle_model": "Car",
            "vehicle_year": 2020,
            "meeting_address": "Toulouse",
            "meeting_lat": 43.61,
            "meeting_lng": 1.45,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Only buyers" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_mechanic_with_buyer_token(
    client: AsyncClient,
    buyer_user: User,
):
    """Test that a buyer cannot access a mechanic-only endpoint."""
    token = buyer_token(buyer_user)
    response = await client.put(
        "/mechanics/me",
        json={"city": "paris"},
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Only mechanics" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_mechanic_no_profile(
    client: AsyncClient,
    db: AsyncSession,
):
    """Test that a mechanic user without a profile gets 404."""
    mech_no_profile = User(
        id=uuid.uuid4(),
        email="noprofile_dep@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000333",
    )
    db.add(mech_no_profile)
    await db.flush()

    token = mechanic_token(mech_no_profile)
    response = await client.put(
        "/mechanics/me",
        json={"city": "paris"},
        headers=auth_header(token),
    )
    assert response.status_code == 404
    assert "Mechanic profile not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_mechanic_deactivated(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a deactivated mechanic gets 403."""
    mechanic_profile.is_active = False
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.put(
        "/mechanics/me",
        json={"city": "paris"},
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_mechanic_suspended(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a suspended mechanic gets 403."""
    mechanic_profile.suspended_until = datetime.now(timezone.utc) + timedelta(days=30)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.put(
        "/mechanics/me",
        json={"city": "paris"},
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "suspended" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_current_mechanic_suspension_expired(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a mechanic whose suspension has expired can access resources."""
    mechanic_profile.suspended_until = datetime.now(timezone.utc) - timedelta(days=1)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.put(
        "/mechanics/me",
        json={"city": "nantes"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["city"] == "nantes"


@pytest.mark.asyncio
async def test_get_current_user_refresh_token_rejected(
    client: AsyncClient,
    buyer_user: User,
):
    """Refresh token cannot be used to access protected endpoints (type != access)."""
    import jwt as pyjwt
    from app.config import settings

    payload = {
        "sub": str(buyer_user.id),
        "type": "refresh",
        "iss": "emecano",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_no_jti_rejected(
    client: AsyncClient,
    buyer_user: User,
):
    """Token without jti claim is rejected."""
    import jwt as pyjwt
    from app.config import settings

    payload = {
        "sub": str(buyer_user.id),
        "type": "access",
        "iss": "emecano",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_blacklisted_token(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
):
    """Blacklisted token is rejected."""
    from app.models.blacklisted_token import BlacklistedToken

    token = create_access_token(str(buyer_user.id))
    # Decode to get jti
    import jwt as pyjwt
    from app.config import settings
    payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                           options={"verify_iss": False})
    jti = payload["jti"]

    # Blacklist the token
    db.add(BlacklistedToken(jti=jti, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    await db.flush()

    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_password_changed_invalidates_token(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
):
    """Token issued before password change is rejected."""
    # Issue token first
    token = create_access_token(str(buyer_user.id))

    # Set password_changed_at to future (simulating password was just changed)
    buyer_user.password_changed_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.flush()

    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 401
    assert "password change" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_admin_with_buyer_token(
    client: AsyncClient,
    buyer_user: User,
):
    """Test that a buyer cannot access an admin-only endpoint.
    Since there's no admin-specific route exposed in the router,
    we test via the dependency directly with a mock endpoint setup.
    """
    # The admin dependency is used in payments or other routes
    # For coverage, we just need the role check to be hit.
    # Let's test it does not work on a mechanic endpoint instead.
    # The admin check is tested by importing and calling the dependency.
    from unittest.mock import AsyncMock, MagicMock

    from fastapi.security import HTTPAuthorizationCredentials

    from app.dependencies import get_current_admin

    # Create a mock that yields our buyer_user and db
    try:
        result = await get_current_admin(user=buyer_user)
        assert False, "Should have raised HTTPException"
    except Exception as e:
        assert e.status_code == 403
        assert "Admin access required" in e.detail


@pytest.mark.asyncio
async def test_get_current_admin_with_admin_user(
    db: AsyncSession,
):
    """Test that an admin user passes the admin check."""
    from app.dependencies import get_current_admin

    admin_user = User(
        id=uuid.uuid4(),
        email="admin@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN,
        phone="+33600000444",
    )
    db.add(admin_user)
    await db.flush()

    result = await get_current_admin(user=admin_user)
    assert result.id == admin_user.id
    assert result.role == UserRole.ADMIN
