import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.services.stripe_service import (
    cancel_payment_intent,
    capture_payment_intent,
    create_connect_account,
    create_payment_intent,
)
from tests.conftest import auth_header, mechanic_token


@pytest.mark.asyncio
async def test_create_payment_intent_mock():
    result = await create_payment_intent(
        amount_cents=5000,
        mechanic_stripe_account_id=None,
        commission_cents=1000,
    )
    assert "id" in result
    assert "client_secret" in result
    assert result["id"].startswith("pi_mock_")


@pytest.mark.asyncio
async def test_cancel_payment_intent_mock():
    # Should not raise
    await cancel_payment_intent("pi_mock_5000")


@pytest.mark.asyncio
async def test_capture_payment_intent_mock():
    await capture_payment_intent("pi_mock_5000")


@pytest.mark.asyncio
async def test_create_connect_account_mock():
    result = await create_connect_account("test@test.com")
    assert "account_id" in result
    assert "onboarding_url" in result


@pytest.mark.asyncio
async def test_onboard_mechanic_endpoint(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    token = mechanic_token(mechanic_user)
    response = await client.post(
        "/payments/onboard-mechanic",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert "onboarding_url" in response.json()


@pytest.mark.asyncio
async def test_onboard_mechanic_already_has_account(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    mechanic_profile.stripe_account_id = "acct_existing"
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.post(
        "/payments/onboard-mechanic",
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_mechanic_dashboard_no_account(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    token = mechanic_token(mechanic_user)
    response = await client.get(
        "/payments/mechanic-dashboard",
        headers=auth_header(token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_mechanic_dashboard_with_account(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    mechanic_profile.stripe_account_id = "acct_mock_123"
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.get(
        "/payments/mechanic-dashboard",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert "dashboard_url" in response.json()


@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature(client: AsyncClient):
    response = await client.post(
        "/payments/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "invalid"},
    )
    assert response.status_code == 400
