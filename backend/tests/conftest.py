import os
import uuid
from collections.abc import AsyncGenerator
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-minimum-32-chars")
os.environ["STRIPE_SECRET_KEY"] = ""  # Force mock mode in tests

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.service import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models.availability import Availability
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User

# Use SQLite for tests (in-memory)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB_URL, echo=False)
test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    # Reset rate limiter storage between tests to avoid 429 errors
    from app.utils.rate_limit import limiter
    if hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "_storage"):
        limiter._limiter._storage.reset()
    elif hasattr(limiter, "reset"):
        limiter.reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def buyer_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000001",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def mechanic_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="mechanic@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000002",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def mechanic_profile(db: AsyncSession, mechanic_user: User) -> MechanicProfile:
    profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=mechanic_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car", "motorcycle"],
        is_identity_verified=True,
        is_active=True,
        stripe_account_id="acct_test_fixture",
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest_asyncio.fixture
async def availability(db: AsyncSession, mechanic_profile: MechanicProfile) -> Availability:
    tomorrow = date.today() + timedelta(days=1)
    avail = Availability(
        id=uuid.uuid4(),
        mechanic_id=mechanic_profile.id,
        date=tomorrow,
        start_time=time(10, 0),
        end_time=time(11, 0),
        is_booked=False,
    )
    db.add(avail)
    await db.flush()
    return avail


def buyer_token(buyer_user: User) -> str:
    return create_access_token(str(buyer_user.id))


def mechanic_token(mechanic_user: User) -> str:
    return create_access_token(str(mechanic_user.id))


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
