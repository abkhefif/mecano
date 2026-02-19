"""Tests for the /health endpoint (AUDIT-FIX3: scheduler status)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check_includes_scheduler_status(client: AsyncClient):
    """Health check returns scheduler status in development mode."""
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    with (
        patch("app.main.async_session", return_value=mock_session),
        patch("app.main.scheduler", mock_scheduler, create=True),
        patch("app.services.scheduler.scheduler", mock_scheduler),
    ):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "scheduler" in data
    assert data["scheduler"] == "running"


@pytest.mark.asyncio
async def test_health_check_scheduler_stopped(client: AsyncClient):
    """Health check reports scheduler as stopped."""
    mock_scheduler = MagicMock()
    mock_scheduler.running = False

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    with (
        patch("app.main.async_session", return_value=mock_session),
        patch("app.services.scheduler.scheduler", mock_scheduler),
    ):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["scheduler"] == "stopped"


@pytest.mark.asyncio
async def test_health_check_db_connected(client: AsyncClient):
    """Health check reports database connected."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with (
        patch("app.main.async_session", return_value=mock_session),
        patch("app.services.scheduler.scheduler", mock_scheduler),
    ):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["database"] == "connected"
    assert data["status"] == "ok"
