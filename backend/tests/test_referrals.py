import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.referral import ReferralCode
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


@pytest.mark.asyncio
async def test_generate_referral_code(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """POST /referrals/generate creates a referral code for a mechanic."""
    token = mechanic_token(mechanic_user)
    response = await client.post(
        "/referrals/generate",
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["code"].startswith("EMECANO-")
    assert data["uses_count"] == 0


@pytest.mark.asyncio
async def test_generate_referral_code_idempotent(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """POST /referrals/generate returns same code if one already exists."""
    token = mechanic_token(mechanic_user)

    # First call creates a code
    response1 = await client.post(
        "/referrals/generate",
        headers=auth_header(token),
    )
    assert response1.status_code == 201
    code1 = response1.json()["code"]

    # Second call returns the same code
    response2 = await client.post(
        "/referrals/generate",
        headers=auth_header(token),
    )
    # May return 201 (idempotent behavior returns existing)
    assert response2.status_code == 201
    code2 = response2.json()["code"]
    assert code1 == code2


@pytest.mark.asyncio
async def test_get_my_referral_code(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """GET /referrals/my-code returns the mechanic's existing referral code."""
    # First create one
    referral = ReferralCode(
        code="EMECANO-TEST01",
        mechanic_id=mechanic_profile.id,
        uses_count=3,
    )
    db.add(referral)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.get(
        "/referrals/my-code",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "EMECANO-TEST01"
    assert data["uses_count"] == 3


@pytest.mark.asyncio
async def test_get_my_referral_code_not_found(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """GET /referrals/my-code returns 404 if no code exists."""
    token = mechanic_token(mechanic_user)
    response = await client.get(
        "/referrals/my-code",
        headers=auth_header(token),
    )
    assert response.status_code == 404
    assert "Generate one first" in response.json()["detail"]


@pytest.mark.asyncio
async def test_validate_referral_code_valid(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_profile: MechanicProfile,
):
    """GET /referrals/validate/{code} returns valid=true for existing code."""
    referral = ReferralCode(
        code="EMECANO-VALID1",
        mechanic_id=mechanic_profile.id,
        uses_count=0,
    )
    db.add(referral)
    await db.flush()

    response = await client.get("/referrals/validate/EMECANO-VALID1")
    assert response.status_code == 200
    assert response.json()["valid"] is True


@pytest.mark.asyncio
async def test_validate_referral_code_invalid(client: AsyncClient):
    """GET /referrals/validate/{code} returns valid=false for non-existent code."""
    response = await client.get("/referrals/validate/EMECANO-NOPE00")
    assert response.status_code == 200
    assert response.json()["valid"] is False


@pytest.mark.asyncio
async def test_generate_referral_only_mechanics(
    client: AsyncClient,
    buyer_user: User,
):
    """Only mechanics can generate referral codes."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/referrals/generate",
        headers=auth_header(token),
    )
    assert response.status_code == 403
