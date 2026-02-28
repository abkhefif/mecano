import pytest
from unittest.mock import AsyncMock, patch

from app.services.notifications import send_booking_reminder, send_email, send_push


@pytest.mark.asyncio
async def test_send_email():
    """send_email logs and returns True."""
    result = await send_email("test@test.com", "Subject", "Body text here")
    assert result is True


@pytest.mark.asyncio
async def test_send_push():
    """send_push returns False when user has no push token (or user not found)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock the DB session to return a user without expo_push_token
    mock_user = MagicMock()
    mock_user.expo_push_token = None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.notifications.async_session", return_value=mock_session_ctx):
        result = await send_push("00000000-0000-0000-0000-000000000001", "Title", "Push body")
    assert result is False


@pytest.mark.asyncio
async def test_send_booking_reminder_24h():
    """send_booking_reminder for 24h sends emails to both parties without phone."""
    with patch("app.services.notifications.send_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = True
        await send_booking_reminder(
            booking_id="booking-123",
            buyer_email="buyer@test.com",
            buyer_name="Jean",
            mechanic_email="mech@test.com",
            mechanic_name="Pierre",
            vehicle_info="Peugeot 308 (2019)",
            meeting_address="123 Rue Test, Toulouse",
            slot_date="2025-06-15",
            slot_time="10:00",
            hours_before=24,
            buyer_phone="+33600000001",
            mechanic_phone="+33600000002",
        )
        assert mock_email.call_count == 2
        # 24h reminder should contain "demain"
        buyer_call = mock_email.call_args_list[0]
        assert "demain" in buyer_call.kwargs["subject"] or "demain" in buyer_call[1].get("subject", "")
        # 24h reminder should NOT include phone contacts
        buyer_body = buyer_call.kwargs.get("body", "") or buyer_call[1].get("body", "")
        assert "+33600000002" not in buyer_body


@pytest.mark.asyncio
async def test_send_booking_reminder_2h_with_phone():
    """send_booking_reminder for 2h sends emails with phone numbers."""
    with patch("app.services.notifications.send_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = True
        await send_booking_reminder(
            booking_id="booking-456",
            buyer_email="buyer@test.com",
            buyer_name="Marie",
            mechanic_email="mech@test.com",
            mechanic_name="Luc",
            vehicle_info="Renault Clio (2020)",
            meeting_address="456 Rue Test, Toulouse",
            slot_date="2025-06-15",
            slot_time="14:00",
            hours_before=2,
            buyer_phone="+33611111111",
            mechanic_phone="+33622222222",
        )
        assert mock_email.call_count == 2
        # 2h reminder should contain "dans 2h"
        buyer_call = mock_email.call_args_list[0]
        buyer_subject = buyer_call.kwargs.get("subject", "")
        assert "dans 2h" in buyer_subject

        # SEC-015: Phone numbers must NOT appear in reminder emails
        buyer_body = buyer_call.kwargs.get("body", "")
        assert "+33622222222" not in buyer_body

        mechanic_call = mock_email.call_args_list[1]
        mechanic_body = mechanic_call.kwargs.get("body", "")
        assert "+33611111111" not in mechanic_body


@pytest.mark.asyncio
async def test_send_booking_reminder_2h_without_phone():
    """send_booking_reminder for 2h works without phone numbers."""
    with patch("app.services.notifications.send_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = True
        await send_booking_reminder(
            booking_id="booking-789",
            buyer_email="buyer@test.com",
            buyer_name="Alice",
            mechanic_email="mech@test.com",
            mechanic_name="Bob",
            vehicle_info="Test Car (2021)",
            meeting_address="Test Address",
            slot_date="2025-06-15",
            slot_time="16:00",
            hours_before=2,
        )
        assert mock_email.call_count == 2
