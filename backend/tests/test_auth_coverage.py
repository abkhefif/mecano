import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, create_refresh_token
from app.models.enums import UserRole
from app.models.user import User
from tests.conftest import auth_header, buyer_token


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
