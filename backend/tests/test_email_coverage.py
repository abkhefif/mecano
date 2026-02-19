"""Coverage tests for email_service.py — targeting uncovered lines.

Tests _get_email_client, decode_email_verification_token, send_password_reset_email,
send_verification_email.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_service import (
    _get_email_client,
    create_email_verification_token,
    decode_email_verification_token,
    send_password_reset_email,
    send_verification_email,
)


# ============ _get_email_client ============


def test_get_email_client_creates_client():
    """First call creates a new httpx.AsyncClient."""
    with patch("app.services.email_service._email_client", None):
        client = _get_email_client()
        assert client is not None
        assert not client.is_closed


def test_get_email_client_recreates_when_closed():
    """Recreates client if the existing one is closed."""
    closed_client = MagicMock()
    closed_client.is_closed = True

    with patch("app.services.email_service._email_client", closed_client):
        client = _get_email_client()
        assert client is not closed_client


# ============ decode_email_verification_token ============


def test_decode_email_verification_token_valid():
    """Round-trip: create then decode an email verification token."""
    email = "test@emecano.fr"
    token = create_email_verification_token(email)
    result = decode_email_verification_token(token)
    assert result == email


def test_decode_email_verification_token_wrong_type():
    """Token with wrong type claim returns None."""
    import jwt
    from app.config import settings

    payload = {
        "sub": "test@emecano.fr",
        "type": "access",  # wrong type
        "iss": "emecano",
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    assert decode_email_verification_token(token) is None


def test_decode_email_verification_token_invalid():
    """Invalid token returns None."""
    assert decode_email_verification_token("not.a.valid.jwt") is None


# ============ send_password_reset_email ============


@pytest.mark.asyncio
async def test_password_reset_no_api_key():
    """Returns False in dev mode (no RESEND_API_KEY)."""
    with patch("app.services.email_service.settings") as mock_s:
        mock_s.RESEND_API_KEY = ""
        result = await send_password_reset_email("user@test.com", "reset_token_123")
    assert result is False


@pytest.mark.asyncio
async def test_password_reset_success():
    """Successful password reset email send."""
    mock_response = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_password_reset_email("user@test.com", "reset_tok")

    assert result is True
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"]
    assert "user@test.com" in payload["to"]
    assert "reset_tok" in payload["html"]


@pytest.mark.asyncio
async def test_password_reset_api_failure():
    """API returns non-success status."""
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_password_reset_email("user@test.com", "tok")

    assert result is False


@pytest.mark.asyncio
async def test_password_reset_exception():
    """Network error returns False."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Network error"))

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_password_reset_email("user@test.com", "tok")

    assert result is False


# ============ send_verification_email ============


@pytest.mark.asyncio
async def test_verification_no_api_key():
    """Returns False in dev mode (no RESEND_API_KEY)."""
    with patch("app.services.email_service.settings") as mock_s:
        mock_s.RESEND_API_KEY = ""
        result = await send_verification_email("user@test.com", "verify_tok")
    assert result is False


@pytest.mark.asyncio
async def test_verification_success():
    """Successful verification email send."""
    mock_response = MagicMock()
    mock_response.is_success = True

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_verification_email("new@test.com", "verify_tok")

    assert result is True
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"]
    assert "new@test.com" in payload["to"]
    assert "verify_tok" in payload["html"]


@pytest.mark.asyncio
async def test_verification_api_failure():
    """API returns non-success status."""
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 429

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_verification_email("user@test.com", "tok")

    assert result is False


@pytest.mark.asyncio
async def test_verification_exception():
    """Network error returns False."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Timeout"))

    with patch("app.services.email_service.settings") as mock_s, \
         patch("app.services.email_service._get_email_client", return_value=mock_client):
        mock_s.RESEND_API_KEY = "re_test_123"
        mock_s.FRONTEND_URL = "https://emecano.fr"
        result = await send_verification_email("user@test.com", "tok")

    assert result is False
