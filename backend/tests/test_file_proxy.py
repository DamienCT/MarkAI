"""Tests for the file proxy endpoint — bucket routing, path traversal, thumbnails."""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app


# Fake 1x1 red PNG (67 bytes) for image tests
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.anyio
async def test_path_traversal_blocked():
    """Paths with .. or backslash should return 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/../etc/passwd")
        assert resp.status_code == 403

        resp = await client.get("/api/v1/files/products\\..\\secret")
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_unknown_bucket_returns_404():
    """Paths not starting with a known bucket or prefix should 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/unknown-bucket/file.png")
        assert resp.status_code == 404


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_products_prefix_uses_default_bucket(mock_download):
    """products/ paths should route to the default MINIO_BUCKET, not a 'products' bucket."""
    mock_download.return_value = _TINY_PNG

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/products/abc-uuid/image.png")

    assert resp.status_code == 200
    # The full path should be passed as object_name, bucket should be the default
    mock_download.assert_called_once()
    _, kwargs = mock_download.call_args
    assert kwargs["bucket"] != "products"
    call_args = mock_download.call_args
    assert call_args[0][0] == "products/abc-uuid/image.png"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_brands_prefix_uses_default_bucket(mock_download):
    """brands/ paths should route to the default bucket."""
    mock_download.return_value = b"fake-image-data"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/brands/brand-id/logos/primary.png")

    assert resp.status_code == 200
    call_args = mock_download.call_args
    assert call_args[0][0] == "brands/brand-id/logos/primary.png"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_content_images_bucket_routes_correctly(mock_download):
    """content-images/ paths should use 'content-images' as the bucket."""
    mock_download.return_value = b"fake-image-data"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/brand/item/mockup.png")

    assert resp.status_code == 200
    call_args = mock_download.call_args
    assert call_args[0][0] == "brand/item/mockup.png"
    assert call_args[1]["bucket"] == "content-images"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_content_type_detection(mock_download):
    """Response Content-Type should match the file extension."""
    mock_download.return_value = b"fake"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/test.jpg")
        assert resp.headers["content-type"] == "image/jpeg"

        resp = await client.get("/api/v1/files/content-images/test.webp")
        assert resp.headers["content-type"] == "image/webp"

        resp = await client.get("/api/v1/files/content-images/test.pdf")
        assert resp.headers["content-type"] == "application/pdf"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_cache_control_header(mock_download):
    """Responses should have Cache-Control header."""
    mock_download.return_value = b"data"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/test.png")

    assert "max-age=3600" in resp.headers.get("cache-control", "")


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_thumbnail_resize(mock_download):
    """?w= parameter should return a smaller image."""
    # Create a real 100x100 PNG for resize testing
    from PIL import Image
    import io

    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    mock_download.return_value = buf.getvalue()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/test.png?w=50&q=70")

    assert resp.status_code == 200
    # Resized image should be smaller than original
    assert len(resp.content) < len(buf.getvalue())
    # Should be served as JPEG (resize converts PNG to JPEG)
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_no_resize_without_param(mock_download):
    """Without ?w= parameter, original image should be returned as-is."""
    original = b"original-png-bytes"
    mock_download.return_value = original

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/test.png")

    assert resp.content == original
