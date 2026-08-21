"""Backend media GETs authenticate with X-Media-Token (MEDIA-TOKEN-FALLBACK).

The agents container fetched product photos and assets from the backend's
/api/v1/files endpoints with no credentials at all — fine while those routes
were public, a guaranteed 401 the moment the backend's media auth is enforced
in production. Every backend media GET now sends X-Media-Token when
MEDIA_PROXY_TOKEN is configured (the shared .env carries it in prod); the
token is NEVER sent to external hosts.
"""

import asyncio
import inspect

import httpx
import pytest

import shared.config as config
import shared.product_swap as product_swap
import shared.tools.storage as storage
from shared.config import media_auth_headers


class _FakeResp:
    status_code = 200
    content = b"png-bytes"

    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    calls: list[tuple[str, dict | None]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, **kwargs):
        _FakeAsyncClient.calls.append((url, headers))
        return _FakeResp()


@pytest.fixture()
def fake_http(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


class TestMediaAuthHeaders:
    def test_blank_token_sends_nothing(self, monkeypatch):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "")
        assert media_auth_headers() == {}

    def test_configured_token_becomes_the_header(self, monkeypatch):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "tok-123")
        assert media_auth_headers() == {"X-Media-Token": "tok-123"}


class TestResolveProductImageBytes:
    def test_files_fallback_sends_the_token(self, monkeypatch, fake_http):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "tok-123")

        async def minio_down(bucket, ref):
            raise RuntimeError("minio unavailable")

        monkeypatch.setattr(storage, "async_download_file", minio_down)
        out = asyncio.run(
            product_swap.resolve_product_image_bytes("products/b1/x.png")
        )
        assert out == b"png-bytes"
        url, headers = fake_http.calls[-1]
        assert url.endswith("/api/v1/files/products/b1/x.png")
        assert headers == {"X-Media-Token": "tok-123"}

    def test_backend_path_sends_the_token(self, monkeypatch, fake_http):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "tok-123")
        out = asyncio.run(
            product_swap.resolve_product_image_bytes("/api/v1/files/x.png")
        )
        assert out == b"png-bytes"
        url, headers = fake_http.calls[-1]
        assert "/api/v1/files/x.png" in url
        assert headers == {"X-Media-Token": "tok-123"}

    def test_external_urls_never_see_the_token(self, monkeypatch, fake_http):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "tok-123")
        out = asyncio.run(
            product_swap.resolve_product_image_bytes("https://cdn.example/x.png")
        )
        assert out == b"png-bytes"
        url, headers = fake_http.calls[-1]
        assert url == "https://cdn.example/x.png"
        assert not headers

    def test_blank_token_sends_empty_headers(self, monkeypatch, fake_http):
        monkeypatch.setattr(config.settings, "MEDIA_PROXY_TOKEN", "")

        async def minio_down(bucket, ref):
            raise RuntimeError("minio unavailable")

        monkeypatch.setattr(storage, "async_download_file", minio_down)
        out = asyncio.run(
            product_swap.resolve_product_image_bytes("products/b1/x.png")
        )
        assert out == b"png-bytes"
        _, headers = fake_http.calls[-1]
        assert not headers  # {} — no bogus header when unset


class TestAllFlaggedCallSitesAreCovered:
    """The four verifier-flagged fetchers all route through the helper."""

    def test_worker_fetchers_send_the_token(self):
        import worker

        assert "media_auth_headers" in inspect.getsource(
            worker._replace_product_in_image
        )
        assert "media_auth_headers" in inspect.getsource(
            worker._download_product_asset
        )

    def test_content_nodes_fetcher_sends_the_token(self):
        import workflows.content.nodes as content_nodes

        assert "media_auth_headers" in inspect.getsource(
            content_nodes._download_product_asset
        )

    def test_product_swap_fetcher_sends_the_token(self):
        assert "media_auth_headers" in inspect.getsource(
            product_swap.resolve_product_image_bytes
        )
