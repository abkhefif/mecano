"""Coverage tests for notifications/routes.py — list, mark read, mark all read."""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models.enums import UserRole
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import TestSessionFactory, engine


@pytest_asyncio.fixture
async def notif_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionFactory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def notif_client(notif_db):
    async def override_get_db():
        yield notif_db

    app.dependency_overrides[get_db] = override_get_db
    from app.utils.rate_limit import limiter
    if hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "_storage"):
        limiter._limiter._storage.reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def notif_user(notif_db):
    user = User(
        id=uuid.uuid4(), email="notif_user@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000100", is_verified=True,
    )
    notif_db.add(user)
    await notif_db.flush()
    return user


@pytest_asyncio.fixture
async def sample_notifications(notif_db, notif_user):
    """Create 3 notifications: 2 unread, 1 read."""
    notifs = []
    for i in range(3):
        n = Notification(
            id=uuid.uuid4(),
            user_id=notif_user.id,
            type="booking_created",
            title=f"Notification {i}",
            body=f"Body {i}",
            is_read=(i == 2),  # Only the last one is read
        )
        notif_db.add(n)
        notifs.append(n)
    await notif_db.flush()
    return notifs


# ============ list_notifications ============


@pytest.mark.asyncio
async def test_list_notifications(notif_client, notif_user, sample_notifications):
    """GET /notifications returns notifications with unread count."""
    token = create_access_token(str(notif_user.id))
    resp = await notif_client.get(
        "/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["notifications"]) == 3
    assert data["unread_count"] == 2


@pytest.mark.asyncio
async def test_list_notifications_with_pagination(notif_client, notif_user, sample_notifications):
    """Pagination with limit and offset."""
    token = create_access_token(str(notif_user.id))
    resp = await notif_client.get(
        "/notifications?limit=2&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["notifications"]) == 2


@pytest.mark.asyncio
async def test_list_notifications_empty(notif_client, notif_user):
    """Empty notification list."""
    token = create_access_token(str(notif_user.id))
    resp = await notif_client.get(
        "/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["notifications"]) == 0
    assert data["unread_count"] == 0


# ============ mark_notification_read ============


@pytest.mark.asyncio
async def test_mark_notification_read(notif_client, notif_user, sample_notifications):
    """PATCH /notifications/{id}/read marks notification as read."""
    notif = sample_notifications[0]
    token = create_access_token(str(notif_user.id))

    resp = await notif_client.patch(
        f"/notifications/{notif.id}/read",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_read"] is True


@pytest.mark.asyncio
async def test_mark_notification_read_not_found(notif_client, notif_user):
    """PATCH /notifications/{random_id}/read returns 404."""
    token = create_access_token(str(notif_user.id))

    resp = await notif_client.patch(
        f"/notifications/{uuid.uuid4()}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_notification_read_not_owner(notif_client, notif_db, sample_notifications):
    """Can't mark another user's notification as read."""
    other_user = User(
        id=uuid.uuid4(), email="other_notif@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000101", is_verified=True,
    )
    notif_db.add(other_user)
    await notif_db.flush()

    notif = sample_notifications[0]
    token = create_access_token(str(other_user.id))

    resp = await notif_client.patch(
        f"/notifications/{notif.id}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ============ mark_all_read ============


@pytest.mark.asyncio
async def test_mark_all_read(notif_client, notif_user, sample_notifications):
    """PATCH /notifications/read-all marks all as read."""
    token = create_access_token(str(notif_user.id))

    resp = await notif_client.patch(
        "/notifications/read-all",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify all are now read
    list_resp = await notif_client.get(
        "/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.json()["unread_count"] == 0
