"""Tests for orphaned files detection and cleanup (AUD5-008).

Tests the scheduler helpers and main detect_orphaned_files job.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduler import (
    _ORPHAN_GRACE_DAYS,
    _collect_db_keys,
    _extract_key_from_url,
    _list_r2_keys,
    detect_orphaned_files,
)


# ============ _extract_key_from_url ============


class TestExtractKeyFromUrl:

    def test_simple_url(self):
        url = "https://cdn.example.com/proofs/abc123.jpg"
        assert _extract_key_from_url(url) == "proofs/abc123.jpg"

    def test_presigned_url(self):
        url = "https://r2.example.com/identity/doc.pdf?X-Amz-Algorithm=AWS4&X-Amz-Credential=abc"
        assert _extract_key_from_url(url) == "identity/doc.pdf"

    def test_nested_path(self):
        url = "https://cdn.example.com/folder/sub/file.png"
        assert _extract_key_from_url(url) == "folder/sub/file.png"

    def test_none(self):
        assert _extract_key_from_url(None) is None

    def test_empty(self):
        assert _extract_key_from_url("") is None

    def test_root_only(self):
        assert _extract_key_from_url("https://example.com/") is None


# ============ _list_r2_keys ============


@pytest.mark.asyncio
async def test_list_r2_keys_not_configured():
    """Returns empty set when R2 is not configured."""
    with patch("app.services.scheduler.settings") as mock_settings:
        mock_settings.R2_ENDPOINT_URL = ""
        result = await _list_r2_keys()
        assert result == set()


@pytest.mark.asyncio
async def test_list_r2_keys_paginated():
    """Lists files across multiple pages."""
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [
        {"Contents": [{"Key": "proofs/a.jpg"}, {"Key": "proofs/b.jpg"}]},
        {"Contents": [{"Key": "identity/c.pdf"}]},
    ]
    mock_client.get_paginator.return_value = mock_paginator

    with patch("app.services.scheduler.settings") as mock_settings, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_settings.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_settings.R2_BUCKET_NAME = "test"
        mock_settings.R2_ACCESS_KEY_ID = "k"
        mock_settings.R2_SECRET_ACCESS_KEY = "s"
        result = await _list_r2_keys()

    assert result == {"proofs/a.jpg", "proofs/b.jpg", "identity/c.pdf"}


@pytest.mark.asyncio
async def test_list_r2_keys_error():
    """Returns empty set on S3 error."""
    mock_client = MagicMock()
    mock_client.get_paginator.side_effect = Exception("S3 down")

    with patch("app.services.scheduler.settings") as mock_settings, \
         patch("app.services.storage.get_s3_client", return_value=mock_client):
        mock_settings.R2_ENDPOINT_URL = "https://r2.example.com"
        mock_settings.R2_BUCKET_NAME = "test"
        mock_settings.R2_ACCESS_KEY_ID = "k"
        mock_settings.R2_SECRET_ACCESS_KEY = "s"
        result = await _list_r2_keys()

    assert result == set()


# ============ detect_orphaned_files (integration) ============


@pytest.mark.asyncio
async def test_detect_no_orphans():
    """No deletions when all R2 files are in DB."""
    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.services.scheduler._list_r2_keys", return_value={"a.jpg", "b.jpg"}), \
         patch("app.services.scheduler._collect_db_keys", return_value={"a.jpg", "b.jpg"}):
        # Should complete without error
        await detect_orphaned_files()


@pytest.mark.asyncio
async def test_detect_orphan_within_grace_period():
    """Orphan file younger than 7 days is NOT deleted."""
    mock_client = MagicMock()
    mock_client.head_object.return_value = {
        "LastModified": datetime.now(timezone.utc) - timedelta(days=3),
    }

    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.services.scheduler._list_r2_keys", return_value={"orphan.jpg"}), \
         patch("app.services.scheduler._collect_db_keys", return_value=set()), \
         patch("app.services.scheduler.async_session"), \
         patch("app.services.storage.get_s3_client", return_value=mock_client), \
         patch("app.services.scheduler.settings") as mock_s:
        mock_s.R2_BUCKET_NAME = "bucket"
        await detect_orphaned_files()

    mock_client.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_detect_orphan_past_grace_period():
    """Orphan file older than 7 days IS deleted."""
    mock_client = MagicMock()
    mock_client.head_object.return_value = {
        "LastModified": datetime.now(timezone.utc) - timedelta(days=10),
    }

    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.services.scheduler._list_r2_keys", return_value={"old.jpg"}), \
         patch("app.services.scheduler._collect_db_keys", return_value=set()), \
         patch("app.services.scheduler.async_session"), \
         patch("app.services.storage.get_s3_client", return_value=mock_client), \
         patch("app.services.scheduler.settings") as mock_s:
        mock_s.R2_BUCKET_NAME = "bucket"
        await detect_orphaned_files()

    mock_client.delete_object.assert_called_once_with(Bucket="bucket", Key="old.jpg")


@pytest.mark.asyncio
async def test_detect_mixed_ages():
    """Only orphans past grace period are deleted; recent ones are skipped."""
    mock_client = MagicMock()
    now = datetime.now(timezone.utc)

    def _head(Bucket, Key):
        if Key == "recent.jpg":
            return {"LastModified": now - timedelta(days=2)}
        return {"LastModified": now - timedelta(days=10)}

    mock_client.head_object.side_effect = _head

    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.services.scheduler._list_r2_keys", return_value={"old1.jpg", "old2.jpg", "recent.jpg"}), \
         patch("app.services.scheduler._collect_db_keys", return_value=set()), \
         patch("app.services.scheduler.async_session"), \
         patch("app.services.storage.get_s3_client", return_value=mock_client), \
         patch("app.services.scheduler.settings") as mock_s:
        mock_s.R2_BUCKET_NAME = "bucket"
        await detect_orphaned_files()

    assert mock_client.delete_object.call_count == 2


@pytest.mark.asyncio
async def test_detect_lock_not_acquired():
    """No-op when scheduler lock is held by another worker."""
    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=False), \
         patch("app.services.scheduler._list_r2_keys") as mock_list:
        await detect_orphaned_files()
        mock_list.assert_not_called()


@pytest.mark.asyncio
async def test_detect_r2_empty():
    """No-op when R2 bucket is empty."""
    with patch("app.services.scheduler._acquire_scheduler_lock", return_value=True), \
         patch("app.services.scheduler._list_r2_keys", return_value=set()), \
         patch("app.services.scheduler._collect_db_keys") as mock_db:
        await detect_orphaned_files()
        mock_db.assert_not_called()
