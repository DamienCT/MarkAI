"""Media auth + hardening (audit P0-08 / addendum §2.4, N-02).

Covers:
- sign_media_path / verify_media_sig HMAC contract (roundtrip, expiry,
  tamper, blank-token fail-closed)
- /api/v1/files auth gate: X-Media-Token, signed mt/exp query, 401 otherwise
- production blank-token behavior (no dev escape)
- hardening headers (nosniff + CSP everywhere; attachment for SVG/PDF)
- brand logo route auth + headers
- deep sensitive-key strip incl. legacy social_credentials (N-02)
- _clean_logo_bytes SVG rejection (server-side fetch path hole)
"""

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.v1.brands import (
    _clean_logo_bytes,
    _looks_like_svg,
    _strip_sensitive_recursive,
)
from app.config import settings
from app.main import app
from app.utils import media_sign
from app.utils.media_sign import (
    media_response_headers,
    sign_media_path,
    verify_media_sig,
)

TOKEN = "test-media-proxy-token"

_TINY_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture()
def media_token(monkeypatch):
    """Configure a media token so the auth gate enforces (blank token falls
    open outside production by design)."""
    monkeypatch.setattr(media_sign, "_media_token", lambda: TOKEN)
    return TOKEN


def _client():
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    )


# ── sign / verify unit contract ─────────────────────────────────────────


def test_sign_verify_roundtrip(media_token):
    path = "/api/v1/files/content-images/abc.png"
    fragment = sign_media_path(path, ttl=60)
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    assert set(params) == {"mt", "exp"}
    assert verify_media_sig(path, params["mt"], params["exp"]) is True


def test_verify_rejects_wrong_path(media_token):
    fragment = sign_media_path("/api/v1/files/a.png", ttl=60)
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    assert verify_media_sig("/api/v1/files/b.png", params["mt"], params["exp"]) is False


def test_verify_rejects_expired(media_token):
    path = "/api/v1/files/a.png"
    fragment = sign_media_path(path, ttl=-10)
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    assert verify_media_sig(path, params["mt"], params["exp"]) is False


def test_verify_rejects_tampered_exp(media_token):
    path = "/api/v1/files/a.png"
    fragment = sign_media_path(path, ttl=30)
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    # Extending exp without re-signing must fail
    forged_exp = str(int(params["exp"]) + 9999)
    assert verify_media_sig(path, params["mt"], forged_exp) is False


def test_verify_rejects_garbage(media_token):
    assert verify_media_sig("/api/v1/files/a.png", "nothex", "notanint") is False
    assert verify_media_sig("/api/v1/files/a.png", "", str(int(time.time()) + 60)) is False


def test_sign_raises_without_token(monkeypatch):
    monkeypatch.setattr(media_sign, "_media_token", lambda: "")
    with pytest.raises(RuntimeError):
        sign_media_path("/api/v1/files/a.png")


def test_verify_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(media_sign, "_media_token", lambda: "")
    assert verify_media_sig("/api/v1/files/a.png", "aa" * 32, str(int(time.time()) + 60)) is False


# ── /files auth gate over HTTP ──────────────────────────────────────────


@pytest.mark.anyio
async def test_files_unauthenticated_rejected_when_token_set(media_token):
    async with _client() as client:
        resp = await client.get("/api/v1/files/content-images/test.png")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_files_wrong_media_token_rejected(media_token):
    async with _client() as client:
        resp = await client.get(
            "/api/v1/files/content-images/test.png",
            headers={"X-Media-Token": "wrong-token"},
        )
    assert resp.status_code == 401


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_media_token_header_accepted(mock_download, media_token):
    mock_download.return_value = _TINY_PNG_BYTES
    async with _client() as client:
        resp = await client.get(
            "/api/v1/files/content-images/test.png",
            headers={"X-Media-Token": TOKEN},
        )
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    # PNG renders inline — no attachment disposition
    assert "content-disposition" not in resp.headers


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_signed_url_accepted(mock_download, media_token):
    mock_download.return_value = _TINY_PNG_BYTES
    path = "/api/v1/files/content-images/signed.png"
    fragment = sign_media_path(path, ttl=60)
    async with _client() as client:
        resp = await client.get(f"{path}?{fragment}")
    assert resp.status_code == 200


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_signed_object_path_accepted(mock_download, media_token):
    """publish_service signs the bare MinIO object path — must verify too."""
    mock_download.return_value = _TINY_PNG_BYTES
    fragment = sign_media_path("content-images/signed.png", ttl=60)
    async with _client() as client:
        resp = await client.get(f"/api/v1/files/content-images/signed.png?{fragment}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_files_signed_url_for_other_path_rejected(media_token):
    fragment = sign_media_path("/api/v1/files/content-images/other.png", ttl=60)
    async with _client() as client:
        resp = await client.get(f"/api/v1/files/content-images/steal.png?{fragment}")
    assert resp.status_code == 401


@pytest.mark.anyio
@patch("app.auth.entra.validate_entra_token", new_callable=AsyncMock)
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_valid_bearer_accepted(mock_download, mock_validate, media_token):
    mock_download.return_value = _TINY_PNG_BYTES
    mock_validate.return_value = {"oid": "user-1"}
    async with _client() as client:
        resp = await client.get(
            "/api/v1/files/content-images/test.png",
            headers={"Authorization": "Bearer some-entra-jwt"},
        )
    assert resp.status_code == 200
    mock_validate.assert_awaited_once()


@pytest.mark.anyio
@patch("app.auth.entra.validate_entra_token", new_callable=AsyncMock)
async def test_files_invalid_bearer_rejected(mock_validate, media_token):
    mock_validate.side_effect = ValueError("bad token")
    async with _client() as client:
        resp = await client.get(
            "/api/v1/files/content-images/test.png",
            headers={"Authorization": "Bearer garbage"},
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_files_blank_token_fails_closed_in_production(monkeypatch):
    monkeypatch.setattr(media_sign, "_media_token", lambda: "")
    monkeypatch.setattr(settings, "MARKAI_ENV", "production")
    async with _client() as client:
        resp = await client.get("/api/v1/files/content-images/test.png")
    assert resp.status_code == 401


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_blank_token_open_outside_production(mock_download, monkeypatch):
    """Local-dev escape: blank token + non-production env keeps media open."""
    mock_download.return_value = _TINY_PNG_BYTES
    monkeypatch.setattr(media_sign, "_media_token", lambda: "")
    async with _client() as client:
        resp = await client.get("/api/v1/files/content-images/test.png")
    assert resp.status_code == 200


# ── hardening headers ───────────────────────────────────────────────────


def test_media_headers_inline_for_raster_and_video():
    for ct in ("image/png", "image/jpeg", "image/webp", "video/mp4"):
        headers = media_response_headers(ct)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        assert "Content-Disposition" not in headers


def test_media_headers_attachment_for_svg_pdf_unknown():
    for ct in ("image/svg+xml", "application/pdf", "application/octet-stream", ""):
        headers = media_response_headers(ct)
        assert headers["Content-Disposition"] == "attachment"
        assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.anyio
@patch("app.services.minio_service.download_file", new_callable=AsyncMock)
async def test_files_svg_served_as_attachment(mock_download, media_token):
    mock_download.return_value = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    async with _client() as client:
        resp = await client.get(
            "/api/v1/files/brand-assets/logo.svg",
            headers={"X-Media-Token": TOKEN},
        )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == "attachment"
    assert "default-src 'none'" in resp.headers["content-security-policy"]


# ── brand logo route ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_logo_route_unauthenticated_rejected(media_token):
    async with _client() as client:
        resp = await client.get(f"/api/v1/brands/{uuid.uuid4()}/logos/primary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_logo_route_serves_with_media_token(media_token):
    brand = SimpleNamespace(
        brand_guidelines={
            "logos": {
                "primary": {
                    "object_name": "brands/x/logos/primary.png",
                    "content_type": "image/png",
                }
            }
        }
    )
    with (
        patch(
            "app.api.v1.brands.brand_service.get_brand",
            new=AsyncMock(return_value=brand),
        ),
        patch(
            "app.api.v1.brands.minio_service.download_file",
            new=AsyncMock(return_value=_TINY_PNG_BYTES),
        ),
    ):
        async with _client() as client:
            resp = await client.get(
                f"/api/v1/brands/{uuid.uuid4()}/logos/primary",
                headers={"X-Media-Token": TOKEN},
            )
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in resp.headers["content-security-policy"]


# ── sensitive-key strip (N-02) ──────────────────────────────────────────


def test_strip_removes_legacy_social_credentials_tokens():
    guidelines = {
        "social_credentials": {
            "meta_access_token": "EAAB-live-token",
            "linkedin_access_token": "AQX-live-token",
            "instagram_account_id": "1789",
            "facebook_page_id": "4242",
        },
        "voice_style": "bold",
    }
    cleaned = _strip_sensitive_recursive(guidelines)
    creds = cleaned["social_credentials"]
    assert "meta_access_token" not in creds
    assert "linkedin_access_token" not in creds
    # Non-secret identifiers survive
    assert creds["instagram_account_id"] == "1789"
    assert creds["facebook_page_id"] == "4242"
    assert cleaned["voice_style"] == "bold"


def test_strip_matches_substring_keys_at_any_depth():
    guidelines = {
        "channels": {
            "instagram": {
                "access_token": "x",
                "page_api_key": "x",
                "MyClientSecret": "x",
                "db_password": "x",
                "handle": "@brand",
            }
        },
        "nested": [{"webhook_url": "https://hooks", "ok": 1}],
    }
    cleaned = _strip_sensitive_recursive(guidelines)
    ig = cleaned["channels"]["instagram"]
    assert set(ig) == {"handle"}
    assert cleaned["nested"][0] == {"ok": 1}


# ── SVG rejection in the logo fetch/store path ──────────────────────────


def test_looks_like_svg_detects_markup():
    assert _looks_like_svg(b"<svg xmlns='...'>") is True
    assert _looks_like_svg(b"  \n<?xml version='1.0'?><svg>") is True
    assert _looks_like_svg(b"<!DOCTYPE html><html>") is True
    assert _looks_like_svg(b"\x89PNG\r\n\x1a\n....") is False
    assert _looks_like_svg(b"\xff\xd8\xff\xe0JFIF") is False


def test_clean_logo_bytes_rejects_svg_content_type():
    with pytest.raises(HTTPException) as exc:
        _clean_logo_bytes(b"\x89PNG\r\n\x1a\n", "image/svg+xml")
    assert exc.value.status_code == 415


def test_clean_logo_bytes_rejects_svg_bytes_with_lying_content_type():
    with pytest.raises(HTTPException) as exc:
        _clean_logo_bytes(b"<svg onload=alert(1)></svg>", "image/png")
    assert exc.value.status_code == 415
