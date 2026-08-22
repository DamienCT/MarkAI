"""Tests for the file proxy endpoint — bucket routing, path traversal, thumbnails.

These run unauthenticated via the non-production blank-token escape,
forced by the autouse fixture below so the developer's local .env (which
may legitimately set MEDIA_PROXY_TOKEN) can't flip these into 401s. The
media auth gate itself is covered in test_media_auth_hardening.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.api.v1.files import parse_range_header
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def _open_media_access(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "")
    monkeypatch.setattr(settings, "MARKAI_ENV", "test")


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
        # URL-encoded so the traversal survives httpx's client-side path
        # normalization and actually reaches the route's own check.
        resp = await client.get("/api/v1/files/%2e%2e%2fetc%2fpasswd")
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
    # w=50 snaps up to the nearest allowed width (64). Assert the actual
    # pixel width — byte size is unreliable: a tiny flat PNG can re-encode
    # to a LARGER JPEG.
    resized = Image.open(io.BytesIO(resp.content))
    assert resized.size[0] == 64
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


@pytest.mark.anyio
async def test_resize_width_rejects_absurd_values():
    """?w= beyond the allowed maximum should be rejected by validation."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/test.png?w=99999")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Range header parsing (pure function — no MinIO needed)
# ---------------------------------------------------------------------------


def test_range_full_range():
    assert parse_range_header("bytes=0-499", 1000) == (0, 499)


def test_range_open_ended():
    assert parse_range_header("bytes=500-", 1000) == (500, 999)


def test_range_suffix():
    """bytes=-N means the last N bytes of the file."""
    assert parse_range_header("bytes=-200", 1000) == (800, 999)


def test_range_suffix_larger_than_file():
    """A suffix longer than the file should clamp to the whole file."""
    assert parse_range_header("bytes=-5000", 1000) == (0, 999)


def test_range_end_clamped_to_file_size():
    assert parse_range_header("bytes=0-99999", 1000) == (0, 999)


def test_range_start_beyond_eof_unsatisfiable():
    assert parse_range_header("bytes=1000-", 1000) is None
    assert parse_range_header("bytes=5000-6000", 1000) is None


def test_range_inverted_is_invalid():
    assert parse_range_header("bytes=500-100", 1000) is None


def test_range_malformed():
    assert parse_range_header("bytes=", 1000) is None
    assert parse_range_header("bytes=-", 1000) is None
    assert parse_range_header("bytes=abc-def", 1000) is None
    assert parse_range_header("seconds=0-10", 1000) is None
    assert parse_range_header("0-499", 1000) is None


def test_range_multi_range_unsupported():
    assert parse_range_header("bytes=0-100,200-300", 1000) is None


def test_range_empty_file():
    assert parse_range_header("bytes=0-", 0) is None


def test_range_whitespace_tolerated():
    assert parse_range_header("  bytes=0-499  ", 1000) == (0, 499)


# ---------------------------------------------------------------------------
# Video streaming with Range support
# ---------------------------------------------------------------------------

_VIDEO_BYTES = b"abcdefghijklmnopqrstuvwxyz"


class _FakeMinioResponse:
    """Mimics the urllib3 response returned by Minio.get_object."""

    def __init__(self, data: bytes):
        self._data = data

    def stream(self, chunk_size):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]

    def close(self):
        pass

    def release_conn(self):
        pass


def _fake_minio_client(data: bytes) -> MagicMock:
    client = MagicMock()
    client.stat_object.return_value = MagicMock(size=len(data))

    def fake_get_object(bucket, object_name, offset=0, length=0):
        end = offset + length if length else len(data)
        return _FakeMinioResponse(data[offset:end])

    client.get_object.side_effect = fake_get_object
    return client


@pytest.mark.anyio
@patch("app.services.minio_service.get_client")
async def test_video_full_request_streams_with_accept_ranges(mock_get_client):
    """Non-Range video request should 200 with Accept-Ranges advertised."""
    mock_get_client.return_value = _fake_minio_client(_VIDEO_BYTES)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/files/content-images/demo/clip.mp4")

    assert resp.status_code == 200
    assert resp.content == _VIDEO_BYTES
    assert resp.headers["content-type"] == "video/mp4"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == str(len(_VIDEO_BYTES))


@pytest.mark.anyio
@patch("app.services.minio_service.get_client")
async def test_video_range_request_returns_206(mock_get_client):
    """Range request should get 206 with Content-Range and only the slice."""
    mock_get_client.return_value = _fake_minio_client(_VIDEO_BYTES)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/files/content-images/demo/clip.mp4",
            headers={"Range": "bytes=2-5"},
        )

    assert resp.status_code == 206
    assert resp.content == _VIDEO_BYTES[2:6]
    assert resp.headers["content-range"] == f"bytes 2-5/{len(_VIDEO_BYTES)}"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == "4"


@pytest.mark.anyio
@patch("app.services.minio_service.get_client")
async def test_video_unsatisfiable_range_returns_416(mock_get_client):
    """A Range past EOF should get 416 with Content-Range: bytes */size."""
    mock_get_client.return_value = _fake_minio_client(_VIDEO_BYTES)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/api/v1/files/content-images/demo/clip.mp4",
            headers={"Range": "bytes=999-"},
        )

    assert resp.status_code == 416
    assert resp.headers["content-range"] == f"bytes */{len(_VIDEO_BYTES)}"
