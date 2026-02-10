import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.services.penalties import apply_no_show_penalty, reset_no_show_if_eligible


@pytest.mark.asyncio
async def test_first_no_show(db: AsyncSession, mechanic_profile: MechanicProfile):
    assert mechanic_profile.no_show_count == 0

    await apply_no_show_penalty(db, mechanic_profile)

    assert mechanic_profile.no_show_count == 1
    assert mechanic_profile.is_active is True
    assert mechanic_profile.suspended_until is None


@pytest.mark.asyncio
async def test_second_no_show_suspension(db: AsyncSession, mechanic_profile: MechanicProfile):
    mechanic_profile.no_show_count = 1
    mechanic_profile.last_no_show_at = datetime.now(timezone.utc) - timedelta(days=10)
    await db.flush()

    await apply_no_show_penalty(db, mechanic_profile)

    assert mechanic_profile.no_show_count == 2
    assert mechanic_profile.suspended_until is not None
    assert mechanic_profile.is_active is True


@pytest.mark.asyncio
async def test_third_no_show_ban(db: AsyncSession, mechanic_profile: MechanicProfile):
    mechanic_profile.no_show_count = 2
    mechanic_profile.last_no_show_at = datetime.now(timezone.utc) - timedelta(days=10)
    await db.flush()

    await apply_no_show_penalty(db, mechanic_profile)

    assert mechanic_profile.no_show_count == 3
    assert mechanic_profile.is_active is False


@pytest.mark.asyncio
async def test_reset_no_show_after_3_months(db: AsyncSession, mechanic_profile: MechanicProfile):
    mechanic_profile.no_show_count = 1
    mechanic_profile.last_no_show_at = datetime.now(timezone.utc) - timedelta(days=100)
    await db.flush()

    await reset_no_show_if_eligible(db, mechanic_profile)

    assert mechanic_profile.no_show_count == 0
    assert mechanic_profile.last_no_show_at is None


@pytest.mark.asyncio
async def test_no_reset_within_3_months(db: AsyncSession, mechanic_profile: MechanicProfile):
    mechanic_profile.no_show_count = 1
    mechanic_profile.last_no_show_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db.flush()

    await reset_no_show_if_eligible(db, mechanic_profile)

    assert mechanic_profile.no_show_count == 1
