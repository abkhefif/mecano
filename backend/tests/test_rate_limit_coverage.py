"""Coverage tests for rate_limit.py — targeting get_real_ip and _get_storage_uri."""
import os
from unittest.mock import MagicMock, patch

from app.utils.rate_limit import get_real_ip, _get_storage_uri


def _make_request(remote_addr: str = "127.0.0.1", forwarded: str | None = None):
    """Helper to build a mock Starlette Request."""
    req = MagicMock()
    req.client.host = remote_addr
    headers = {}
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded
    req.headers = headers
    return req


def test_get_real_ip_no_proxy():
    """Without trusted proxies, returns direct connection IP."""
    with patch.dict(os.environ, {"TRUSTED_PROXY_COUNT": "0"}):
        req = _make_request(remote_addr="192.168.1.1")
        with patch("app.utils.rate_limit.get_remote_address", return_value="192.168.1.1"):
            ip = get_real_ip(req)
    assert ip == "192.168.1.1"


def test_get_real_ip_single_proxy():
    """With 1 trusted proxy, index = len(ips) - 1 picks the IP at that position."""
    with patch.dict(os.environ, {"TRUSTED_PROXY_COUNT": "1"}):
        # ips = ["10.0.0.1", "192.168.1.1"], index = max(0, 2-1) = 1
        req = _make_request(forwarded="10.0.0.1, 192.168.1.1")
        ip = get_real_ip(req)
    assert ip == "192.168.1.1"


def test_get_real_ip_two_proxies():
    """With 2 trusted proxies, index = len(ips) - 2 picks the correct IP."""
    with patch.dict(os.environ, {"TRUSTED_PROXY_COUNT": "2"}):
        # ips = ["1.1.1.1", "10.0.0.1", "192.168.1.1"], index = max(0, 3-2) = 1
        req = _make_request(forwarded="1.1.1.1, 10.0.0.1, 192.168.1.1")
        ip = get_real_ip(req)
    assert ip == "10.0.0.1"


def test_get_real_ip_proxy_no_forwarded():
    """With trusted proxy but no X-Forwarded-For, falls back to remote address."""
    with patch.dict(os.environ, {"TRUSTED_PROXY_COUNT": "1"}):
        req = _make_request(remote_addr="172.16.0.1")
        with patch("app.utils.rate_limit.get_remote_address", return_value="172.16.0.1"):
            ip = get_real_ip(req)
    assert ip == "172.16.0.1"


def test_get_real_ip_proxy_single_ip_in_chain():
    """With 1 trusted proxy and only 1 IP in chain, returns that IP."""
    with patch.dict(os.environ, {"TRUSTED_PROXY_COUNT": "1"}):
        req = _make_request(forwarded="203.0.113.50")
        ip = get_real_ip(req)
    assert ip == "203.0.113.50"


# ============ _get_storage_uri ============


def test_get_storage_uri_with_redis():
    """Returns Redis URL when configured for production."""
    with patch("app.config.settings") as mock_s:
        mock_s.REDIS_URL = "redis://redis.prod.internal:6379/0"
        result = _get_storage_uri()
    assert result == "redis://redis.prod.internal:6379/0"


def test_get_storage_uri_with_localhost_redis():
    """Returns None when Redis URL contains localhost."""
    with patch("app.config.settings") as mock_s:
        mock_s.REDIS_URL = "redis://localhost:6379/0"
        result = _get_storage_uri()
    assert result is None


def test_get_storage_uri_import_error():
    """Returns None when settings import fails."""
    with patch("app.config.settings", new_callable=lambda: MagicMock(side_effect=AttributeError)):
        # Force an exception inside _get_storage_uri by making settings raise
        pass
    # Simpler approach: just verify it handles exceptions gracefully
    # The except branch catches any Exception, so we mock settings.REDIS_URL to raise
    mock_settings = MagicMock()
    type(mock_settings).REDIS_URL = property(lambda self: (_ for _ in ()).throw(RuntimeError("fail")))
    with patch("app.config.settings", mock_settings):
        result = _get_storage_uri()
    assert result is None
