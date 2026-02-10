"""Tests for app/services/storage.py and app/services/stripe_service.py."""

import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.storage import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE,
    get_s3_client,
    upload_file,
    upload_file_bytes,
)
from app.services.stripe_service import (
    cancel_payment_intent,
    capture_payment_intent,
    create_connect_account,
    create_login_link,
    create_payment_intent,
    verify_webhook_signature,
)


def _make_upload_file(filename: str, content: bytes, content_type: str) -> UploadFile:
    """Create an UploadFile with the given content type."""
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


# ============ storage.py tests ============


@pytest.mark.asyncio
async def test_upload_file_valid_jpeg():
    """Test uploading a valid JPEG file in dev mode (no R2 endpoint)."""
    file = _make_upload_file("test.jpg", b"\xff\xd8\xff" + b"fake-jpeg-content", "image/jpeg")

    url = await upload_file(file, "proofs")
    assert url.startswith("https://storage.emecano.dev/proofs/")
    assert url.endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_file_valid_png():
    """Test uploading a valid PNG file in dev mode."""
    file = _make_upload_file("test.png", b"\x89PNG" + b"fake-png-content", "image/png")

    url = await upload_file(file, "identity")
    assert url.startswith("https://storage.emecano.dev/identity/")
    assert url.endswith(".png")


@pytest.mark.asyncio
async def test_upload_file_invalid_content_type():
    """Test uploading a file with an unsupported content type."""
    file = _make_upload_file("test.pdf", b"content", "application/pdf")

    with pytest.raises(ValueError, match="not allowed"):
        await upload_file(file, "proofs")


@pytest.mark.asyncio
async def test_upload_file_too_large():
    """Test uploading a file that exceeds the size limit."""
    content = b"x" * (MAX_FILE_SIZE + 1)
    file = _make_upload_file("big.jpg", content, "image/jpeg")

    with pytest.raises(ValueError, match="too large"):
        await upload_file(file, "proofs")


@pytest.mark.asyncio
async def test_upload_file_with_r2_endpoint():
    """Test uploading a file when R2_ENDPOINT_URL is configured (production mode)."""
    file = _make_upload_file("test.jpg", b"\xff\xd8\xff" + b"fake-jpeg-content", "image/jpeg")

    mock_client = MagicMock()

    with patch("app.services.storage.settings") as mock_settings, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_settings.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_settings.R2_BUCKET_NAME = "test-bucket"
        mock_settings.R2_PUBLIC_URL = "https://cdn.example.com"
        mock_settings.R2_ACCESS_KEY_ID = "key"
        mock_settings.R2_SECRET_ACCESS_KEY = "secret"

        url = await upload_file(file, "proofs")

        assert url.startswith("https://cdn.example.com/proofs/")
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["ContentType"] == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_file_bytes_dev_mode():
    """Test upload_file_bytes in dev mode (no R2 endpoint)."""
    url = await upload_file_bytes(b"pdf-bytes", "reports/test.pdf", "application/pdf")
    assert url == "https://storage.emecano.dev/reports/test.pdf"


@pytest.mark.asyncio
async def test_upload_file_bytes_with_r2():
    """Test upload_file_bytes when R2_ENDPOINT_URL is configured."""
    mock_client = MagicMock()

    with patch("app.services.storage.settings") as mock_settings, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_settings.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_settings.R2_BUCKET_NAME = "test-bucket"
        mock_settings.R2_PUBLIC_URL = "https://cdn.example.com"
        mock_settings.R2_ACCESS_KEY_ID = "key"
        mock_settings.R2_SECRET_ACCESS_KEY = "secret"

        url = await upload_file_bytes(
            b"pdf-content", "reports/test.pdf", "application/pdf"
        )

        assert url == "https://cdn.example.com/reports/test.pdf"
        mock_client.put_object.assert_called_once()


def test_get_s3_client_without_endpoint():
    """Test get_s3_client when R2_ENDPOINT_URL is empty."""
    with patch("app.services.storage.settings") as mock_settings, \
         patch("app.services.storage.boto3") as mock_boto3:
        mock_settings.R2_ENDPOINT_URL = ""
        mock_settings.R2_ACCESS_KEY_ID = "key"
        mock_settings.R2_SECRET_ACCESS_KEY = "secret"

        get_s3_client()

        call_kwargs = mock_boto3.client.call_args[1]
        assert "endpoint_url" not in call_kwargs


def test_get_s3_client_with_endpoint():
    """Test get_s3_client when R2_ENDPOINT_URL is set."""
    with patch("app.services.storage.settings") as mock_settings, \
         patch("app.services.storage.boto3") as mock_boto3:
        mock_settings.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_settings.R2_ACCESS_KEY_ID = "key"
        mock_settings.R2_SECRET_ACCESS_KEY = "secret"

        get_s3_client()

        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "https://r2.example.com"


# ============ stripe_service.py tests ============


@pytest.mark.asyncio
async def test_create_payment_intent_dev_mode():
    """Test payment intent creation in dev mode (empty STRIPE_SECRET_KEY)."""
    result = await create_payment_intent(
        amount_cents=5000,
        mechanic_stripe_account_id=None,
        commission_cents=1000,
    )
    assert result["id"] == "pi_mock_5000"
    assert "client_secret" in result


@pytest.mark.asyncio
async def test_create_payment_intent_with_stripe():
    """Test payment intent creation when Stripe is configured."""
    mock_intent = MagicMock()
    mock_intent.id = "pi_real_123"
    mock_intent.client_secret = "pi_real_123_secret_abc"

    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
        mock_stripe.PaymentIntent.create.return_value = mock_intent

        result = await create_payment_intent(
            amount_cents=5000,
            mechanic_stripe_account_id="acct_123",
            commission_cents=1000,
            metadata={"test": "data"},
        )

        assert result["id"] == "pi_real_123"
        assert result["client_secret"] == "pi_real_123_secret_abc"
        call_kwargs = mock_stripe.PaymentIntent.create.call_args[1]
        assert call_kwargs["amount"] == 5000
        assert call_kwargs["transfer_data"]["destination"] == "acct_123"
        assert call_kwargs["application_fee_amount"] == 1000


@pytest.mark.asyncio
async def test_create_payment_intent_without_mechanic_account():
    """Test payment intent creation without a mechanic Stripe account."""
    mock_intent = MagicMock()
    mock_intent.id = "pi_real_456"
    mock_intent.client_secret = "pi_real_456_secret_def"

    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
        mock_stripe.PaymentIntent.create.return_value = mock_intent

        result = await create_payment_intent(
            amount_cents=5000,
            mechanic_stripe_account_id=None,
            commission_cents=1000,
        )

        call_kwargs = mock_stripe.PaymentIntent.create.call_args[1]
        assert "transfer_data" not in call_kwargs
        assert "application_fee_amount" not in call_kwargs


@pytest.mark.asyncio
async def test_cancel_payment_intent_dev_mode():
    """Test cancellation in dev mode with mock payment intent."""
    await cancel_payment_intent("pi_mock_5000")


@pytest.mark.asyncio
async def test_cancel_payment_intent_with_stripe():
    """Test cancellation when Stripe is configured."""
    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"

        await cancel_payment_intent("pi_real_123")
        mock_stripe.PaymentIntent.cancel.assert_called_once_with("pi_real_123")


@pytest.mark.asyncio
async def test_capture_payment_intent_dev_mode():
    """Test capture in dev mode with mock payment intent."""
    await capture_payment_intent("pi_mock_5000")


@pytest.mark.asyncio
async def test_capture_payment_intent_with_stripe():
    """Test capture when Stripe is configured."""
    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"

        await capture_payment_intent("pi_real_123")
        mock_stripe.PaymentIntent.capture.assert_called_once_with("pi_real_123")


@pytest.mark.asyncio
async def test_create_connect_account_dev_mode():
    """Test Connect account creation in dev mode."""
    result = await create_connect_account("test@example.com")
    assert result["account_id"] == "acct_mock_123"
    assert "onboarding_url" in result


@pytest.mark.asyncio
async def test_create_connect_account_with_stripe():
    """Test Connect account creation when Stripe is configured."""
    mock_account = MagicMock()
    mock_account.id = "acct_real_123"

    mock_link = MagicMock()
    mock_link.url = "https://connect.stripe.com/onboarding/real"

    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
        mock_stripe.Account.create.return_value = mock_account
        mock_stripe.AccountLink.create.return_value = mock_link

        result = await create_connect_account("mechanic@test.com")

        assert result["account_id"] == "acct_real_123"
        assert result["onboarding_url"] == "https://connect.stripe.com/onboarding/real"


@pytest.mark.asyncio
async def test_create_login_link_dev_mode():
    """Test login link in dev mode with mock account."""
    url = await create_login_link("acct_mock_123")
    assert url == "https://connect.stripe.com/mock-dashboard"


@pytest.mark.asyncio
async def test_create_login_link_with_stripe():
    """Test login link when Stripe is configured."""
    mock_link = MagicMock()
    mock_link.url = "https://connect.stripe.com/dashboard/real"

    with patch("app.services.stripe_service.settings") as mock_settings, \
         patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
        mock_stripe.Account.create_login_link.return_value = mock_link

        url = await create_login_link("acct_real_456")
        assert url == "https://connect.stripe.com/dashboard/real"


def test_verify_webhook_signature():
    """Test webhook signature verification delegates to stripe."""
    with patch("app.services.stripe_service.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = {"type": "test"}

        result = verify_webhook_signature(b"payload", "sig_header")
        assert result == {"type": "test"}
        mock_stripe.Webhook.construct_event.assert_called_once()
