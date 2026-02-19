"""Coverage tests for notifications.py — targeting uncovered lines.

Tests send_email (Resend API), send_push (Expo Push API), create_notification.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    _get_push_client,
    create_notification,
    send_email,
    send_push,
)


# ============ _get_push_client ============


def test_get_push_client_creates_client():
    """First call creates a new httpx.AsyncClient."""
    with patch("app.services.notifications._push_client", None):
        client = _get_push_client()
        assert client is not None
        assert not client.is_closed


def test_get_push_client_reuses_open_client():
    """Subsequent calls reuse the same client."""
    with patch("app.services.notifications._push_client", None):
        c1 = _get_push_client()
        # Patch the global to the returned client
        with patch("app.services.notifications._push_client", c1):
            c2 = _get_push_client()
        assert c1 is c2


# ============ send_email ============


@pytest.mark.asyncio
async def test_send_email_dev_mode():
    """In dev mode (no RESEND_API_KEY), returns True without sending."""
    with patch("app.services.notifications.settings") as mock_s:
        mock_s.RESEND_API_KEY = ""
        result = await send_email("user@test.com", "Subject", "Body")
    assert result is True


@pytest.mark.asyncio
async def test_send_email_success():
    """Successful email send via Resend API."""
    mock_response = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications.settings") as mock_s, \
         patch("app.services.notifications._get_push_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        result = await send_email("user@test.com", "Welcome", "<h1>Hi</h1>")

    assert result is True
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["json"]["to"] == ["user@test.com"]


@pytest.mark.asyncio
async def test_send_email_api_failure():
    """API returns non-success status code."""
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 422

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications.settings") as mock_s, \
         patch("app.services.notifications._get_push_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        result = await send_email("bad@test.com", "Fail", "body")

    assert result is False


@pytest.mark.asyncio
async def test_send_email_exception():
    """Network error during email send returns False."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("app.services.notifications.settings") as mock_s, \
         patch("app.services.notifications._get_push_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        result = await send_email("err@test.com", "Error", "body")

    assert result is False


# ============ send_push ============


@pytest.mark.asyncio
async def test_send_push_no_token():
    """Returns False when user has no push token."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await send_push(user_id, "Title", "Body", db=mock_session)
    assert result is False


@pytest.mark.asyncio
async def test_send_push_no_user():
    """Returns False when user not found in DB."""
    user_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await send_push(user_id, "Title", "Body", db=mock_session)
    assert result is False


@pytest.mark.asyncio
async def test_send_push_success():
    """Successful push notification send."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[abc123]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"status": "ok", "id": "ticket_123"}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        result = await send_push(user_id, "Hello", "World", db=mock_session)

    assert result is True
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["to"] == "ExponentPushToken[abc123]"
    assert payload["title"] == "Hello"


@pytest.mark.asyncio
async def test_send_push_truncates_long_text():
    """Title and body are truncated to 50 and 200 chars respectively."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[xyz]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"status": "ok"}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    long_title = "A" * 100
    long_body = "B" * 500

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        await send_push(user_id, long_title, long_body, db=mock_session)

    payload = mock_client.post.call_args[1]["json"]
    assert len(payload["title"]) == 50
    assert len(payload["body"]) == 200


@pytest.mark.asyncio
async def test_send_push_with_booking_data():
    """Push with booking_created data includes categoryId."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[cat]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"status": "ok"}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        await send_push(user_id, "New Booking", "Details", data={"type": "booking_created"}, db=mock_session)

    payload = mock_client.post.call_args[1]["json"]
    assert payload["categoryId"] == "booking_request"
    assert payload["data"]["type"] == "booking_created"


@pytest.mark.asyncio
async def test_send_push_device_not_registered():
    """DeviceNotRegistered clears the user's push token."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[old]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "status": "error",
            "message": "Token not registered",
            "details": {"error": "DeviceNotRegistered"},
        }
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        result = await send_push(user_id, "Title", "Body", db=mock_session)

    assert result is True
    assert mock_user.expo_push_token is None
    mock_session.flush.assert_called()


@pytest.mark.asyncio
async def test_send_push_ticket_error_other():
    """Non-DeviceNotRegistered ticket error is logged but push succeeds."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[err]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "status": "error",
            "message": "Some other error",
            "details": {"error": "InvalidCredentials"},
        }
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        result = await send_push(user_id, "Title", "Body", db=mock_session)

    assert result is True
    # Token should NOT be cleared
    assert mock_user.expo_push_token == "ExponentPushToken[err]"


@pytest.mark.asyncio
async def test_send_push_receipt_parse_error():
    """JSON parse error in receipt doesn't fail the overall push."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[parse]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = Exception("Invalid JSON")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.notifications._get_push_client", return_value=mock_client):
        result = await send_push(user_id, "Title", "Body", db=mock_session)

    assert result is True


@pytest.mark.asyncio
async def test_send_push_without_db_session():
    """send_push opens its own session when db=None."""
    user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.expo_push_token = "ExponentPushToken[nodb]"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"status": "ok"}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    # Mock async_session context manager
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.notifications._get_push_client", return_value=mock_client), \
         patch("app.services.notifications.async_session", return_value=mock_ctx):
        result = await send_push(user_id, "Title", "Body", db=None)

    assert result is True


@pytest.mark.asyncio
async def test_send_push_exception_returns_false():
    """General exception in send_push returns False."""
    user_id = str(uuid.uuid4())

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("DB error"))

    result = await send_push(user_id, "Title", "Body", db=mock_session)
    assert result is False


# ============ create_notification ============


@pytest.mark.asyncio
async def test_create_notification_basic():
    """create_notification persists notification and fires push task."""
    user_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    with patch("app.services.notifications.send_push") as mock_push, \
         patch("asyncio.create_task") as mock_task:
        notif = await create_notification(
            db=mock_session,
            user_id=user_id,
            notification_type="booking_created",
            title="New Booking",
            body="You have a new booking request",
            data={"booking_id": "123"},
        )

    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()
    mock_task.assert_called_once()
    assert notif.title == "New Booking"
    assert notif.data["type"] == "booking_created"


@pytest.mark.asyncio
async def test_create_notification_with_enum_type():
    """create_notification handles enum notification types."""
    from app.models.enums import NotificationType

    user_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    with patch("asyncio.create_task"):
        notif = await create_notification(
            db=mock_session,
            user_id=user_id,
            notification_type=NotificationType.BOOKING_CONFIRMED,
            title="Confirmed",
            body="Booking confirmed",
        )

    # push_data should contain the string value of the enum
    assert notif.data["type"] == "booking_confirmed"


@pytest.mark.asyncio
async def test_create_notification_data_already_has_type():
    """If data dict already contains 'type', it's preserved."""
    user_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    with patch("asyncio.create_task"):
        notif = await create_notification(
            db=mock_session,
            user_id=user_id,
            notification_type="booking_created",
            title="Title",
            body="Body",
            data={"type": "custom_type", "extra": "data"},
        )

    # Original type in data should be preserved
    assert notif.data["type"] == "custom_type"
    assert notif.data["extra"] == "data"
