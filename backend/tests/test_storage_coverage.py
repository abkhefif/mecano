"""Coverage tests for storage.py — targeting uncovered lines.

Tests presigned URLs, get_key_from_url, get_sensitive_url, upload_file_bytes validation.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.storage import (
    MAX_FILE_BYTES_SIZE,
    generate_presigned_url,
    get_key_from_url,
    get_sensitive_url,
    upload_file_bytes,
    _validate_magic_bytes,
)


# ============ _validate_magic_bytes ============


def test_validate_magic_bytes_jpeg():
    assert _validate_magic_bytes(b"\xff\xd8\xff\xe0rest", "image/jpeg") is True


def test_validate_magic_bytes_png():
    assert _validate_magic_bytes(b"\x89PNGrest", "image/png") is True


def test_validate_magic_bytes_pdf():
    assert _validate_magic_bytes(b"%PDF-1.4 rest", "application/pdf") is True


def test_validate_magic_bytes_mismatch():
    assert _validate_magic_bytes(b"not a jpeg", "image/jpeg") is False


def test_validate_magic_bytes_unknown_type():
    assert _validate_magic_bytes(b"anything", "application/octet-stream") is False


# ============ get_key_from_url ============


def test_get_key_from_url_with_public_url():
    """Extract key from public R2 URL."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        result = get_key_from_url("https://cdn.emecano.fr/proofs/abc123.jpg")
    assert result == "proofs/abc123.jpg"


def test_get_key_from_url_mock_url():
    """Extract key from dev mock URL (R2_PUBLIC_URL must be non-empty to pass guard)."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        result = get_key_from_url("https://storage.emecano.dev/identity/doc.pdf")
    assert result == "identity/doc.pdf"


def test_get_key_from_url_empty():
    """Returns None for empty URL."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        result = get_key_from_url("")
    assert result is None


def test_get_key_from_url_unrecognized():
    """Returns None for unrecognized URL format."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        result = get_key_from_url("https://other.com/file.jpg")
    assert result is None


# ============ generate_presigned_url ============


@pytest.mark.asyncio
async def test_generate_presigned_url_dev_mode():
    """Returns mock presigned URL in dev mode."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_ENDPOINT_URL = ""
        url = await generate_presigned_url("proofs/abc.jpg", expires_in=900)
    assert "presigned=mock" in url
    assert "proofs/abc.jpg" in url


@pytest.mark.asyncio
async def test_generate_presigned_url_real():
    """Calls S3 generate_presigned_url in production mode."""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://r2.example.com/proofs/abc.jpg?signed"

    with patch("app.services.storage.settings") as mock_s, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_s.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_s.R2_BUCKET_NAME = "test-bucket"
        url = await generate_presigned_url("proofs/abc.jpg", expires_in=600)

    assert "signed" in url


# ============ get_sensitive_url ============


@pytest.mark.asyncio
async def test_get_sensitive_url_none():
    """Returns None for None input."""
    result = await get_sensitive_url(None)
    assert result is None


@pytest.mark.asyncio
async def test_get_sensitive_url_empty():
    """Returns None for empty input."""
    result = await get_sensitive_url("")
    assert result is None


@pytest.mark.asyncio
async def test_get_sensitive_url_no_key():
    """Returns original URL if key can't be extracted."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        result = await get_sensitive_url("https://other.com/file.jpg")
    assert result == "https://other.com/file.jpg"


@pytest.mark.asyncio
async def test_get_sensitive_url_converts():
    """Converts public URL to presigned URL."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        mock_s.R2_ENDPOINT_URL = ""
        result = await get_sensitive_url("https://storage.emecano.dev/identity/doc.pdf")
    assert "presigned=mock" in result


# ============ upload_file_bytes ============


@pytest.mark.asyncio
async def test_upload_file_bytes_too_large():
    """Raises ValueError for oversized content."""
    content = b"x" * (MAX_FILE_BYTES_SIZE + 1)
    with pytest.raises(ValueError, match="Content too large"):
        await upload_file_bytes(content, "reports/test.pdf", "application/pdf")


@pytest.mark.asyncio
async def test_upload_file_bytes_dev_mode():
    """Returns mock URL in dev mode."""
    with patch("app.services.storage.settings") as mock_s:
        mock_s.R2_ENDPOINT_URL = ""
        url = await upload_file_bytes(b"%PDF-1.4 test", "reports/test.pdf", "application/pdf")
    assert url == "https://storage.emecano.dev/reports/test.pdf"


@pytest.mark.asyncio
async def test_upload_file_bytes_real():
    """Uploads to S3 in production mode."""
    mock_client = MagicMock()

    with patch("app.services.storage.settings") as mock_s, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_s.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_s.R2_BUCKET_NAME = "test-bucket"
        mock_s.R2_PUBLIC_URL = "https://cdn.emecano.fr"
        url = await upload_file_bytes(b"%PDF-1.4 test", "reports/test.pdf", "application/pdf")

    assert url == "https://cdn.emecano.fr/reports/test.pdf"
    mock_client.put_object.assert_called_once()


# ============ upload_file with folder validation ============


@pytest.mark.asyncio
async def test_upload_file_invalid_folder():
    """Raises ValueError for disallowed upload folder."""
    from app.services.storage import upload_file
    from unittest.mock import AsyncMock

    mock_file = MagicMock()
    mock_file.content_type = "image/jpeg"
    mock_file.size = 1000

    with pytest.raises(ValueError, match="not allowed"):
        await upload_file(mock_file, "../../etc")


@pytest.mark.asyncio
async def test_upload_file_invalid_content_type():
    """Raises ValueError for disallowed content type."""
    from app.services.storage import upload_file

    mock_file = MagicMock()
    mock_file.content_type = "application/zip"
    mock_file.size = 1000

    with pytest.raises(ValueError, match="not allowed"):
        await upload_file(mock_file, "identity")


@pytest.mark.asyncio
async def test_upload_file_too_large_header():
    """Raises ValueError when file.size exceeds limit."""
    from app.services.storage import upload_file, MAX_FILE_SIZE

    mock_file = MagicMock()
    mock_file.content_type = "image/jpeg"
    mock_file.size = MAX_FILE_SIZE + 1

    with pytest.raises(ValueError, match="File too large"):
        await upload_file(mock_file, "identity")
