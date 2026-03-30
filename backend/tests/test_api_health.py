"""Tests for the /health endpoint and app creation."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_health_endpoint():
    """The /health endpoint should return 200 with status ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_app_title():
    """The FastAPI app should have the expected title."""
    assert app.title == "MARKAI API"


def test_app_version():
    """The FastAPI app should have a version string."""
    assert app.version == "0.1.0"
