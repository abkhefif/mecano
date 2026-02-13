import pytest
from starlette.testclient import TestClient

from app.middleware import SecurityHeadersMiddleware


@pytest.mark.asyncio
async def test_security_headers_middleware():
    """SecurityHeadersMiddleware adds all security headers to responses."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from httpx import ASGITransport, AsyncClient

    async def homepage(request: Request):
        return PlainTextResponse("OK")

    test_app = Starlette(routes=[Route("/", homepage)])
    test_app.add_middleware(SecurityHeadersMiddleware)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
