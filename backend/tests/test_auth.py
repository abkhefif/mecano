import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_register_buyer(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "newbuyer@test.com",
            "password": "SecurePass123",
            "role": "buyer",
            "phone": "+33600000010",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_mechanic(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "newmechanic@test.com",
            "password": "SecurePass123",
            "role": "mechanic",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, buyer_user: User):
    response = await client.post(
        "/auth/register",
        json={
            "email": "buyer@test.com",
            "password": "SecurePass123",
            "role": "buyer",
            "cgu_accepted": True,
        },
    )
    # H-02: Don't reveal email existence - return same 201 as success
    assert response.status_code == 201
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_register_invalid_password(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "short@test.com",
            "password": "short",
            "role": "buyer",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, buyer_user: User):
    response = await client.post(
        "/auth/login",
        json={"email": "buyer@test.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, buyer_user: User):
    response = await client.post(
        "/auth/login",
        json={"email": "buyer@test.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient):
    response = await client.post(
        "/auth/login",
        json={"email": "nobody@test.com", "password": "password123"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, buyer_user: User):
    from tests.conftest import auth_header, buyer_token

    token = buyer_token(buyer_user)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "buyer@test.com"
    assert data["role"] == "buyer"


@pytest.mark.asyncio
async def test_get_me_mechanic_with_profile(
    client: AsyncClient, mechanic_user: User, mechanic_profile
):
    from tests.conftest import auth_header, mechanic_token

    token = mechanic_token(mechanic_user)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "mechanic"
    assert data["mechanic_profile"] is not None
    assert data["mechanic_profile"]["city"] == "toulouse"


@pytest.mark.asyncio
async def test_get_me_no_token(client: AsyncClient):
    response = await client.get("/auth/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    response = await client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401


# ---- Additional tests for coverage ----


@pytest.mark.asyncio
async def test_register_mechanic_creates_profile(client: AsyncClient):
    """Test that registering as a mechanic also creates a MechanicProfile."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "newmech_profile@test.com",
            "password": "SecurePass123",
            "role": "mechanic",
            "phone": "+33600000999",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    # Verify the profile was created via /auth/me
    me_response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["role"] == "mechanic"
    assert data["mechanic_profile"] is not None


@pytest.mark.asyncio
async def test_register_buyer_with_phone(client: AsyncClient):
    """Test registering a buyer with a phone number."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "buyerphone@test.com",
            "password": "SecurePass123",
            "role": "buyer",
            "phone": "+33600000888",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    me_response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["phone"] == "+33600000888"


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Test registering with an invalid email address."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": "SecurePass123",
            "role": "buyer",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_role(client: AsyncClient):
    """Test registering with an invalid role."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "role@test.com",
            "password": "SecurePass123",
            "role": "invalid_role",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_returns_valid_token(client: AsyncClient, buyer_user: User):
    """Test that the login token can be used to access protected endpoints."""
    login_response = await client.post(
        "/auth/login",
        json={"email": "buyer@test.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "buyer@test.com"


@pytest.mark.asyncio
async def test_get_me_buyer_no_profile(client: AsyncClient, buyer_user: User):
    """Test /auth/me for a buyer (should have mechanic_profile=None)."""
    from tests.conftest import auth_header, buyer_token

    token = buyer_token(buyer_user)
    response = await client.get("/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "buyer"
    assert data["mechanic_profile"] is None
