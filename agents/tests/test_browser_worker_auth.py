"""Browser-worker auth failures are loud, never silently bypassed
(BROWSER-CLIENT-LOUD).

The client used to send the placeholder "internal" as X-API-Key when
BROWSER_WORKER_API_KEY was blank, and any worker error — including 401/403 —
silently fell back to direct unguarded HTTP, quietly bypassing the worker's
SSRF/auth guards. Now: a blank key logs one ERROR naming the
misconfiguration, a 401/403 raises BrowserWorkerAuthError with no fallback,
and only genuine unavailability (connect error/timeout/5xx) keeps the
direct-fetch fallback.
"""

import asyncio
import logging

import httpx
import pytest

import shared.tools.browser as browser
from shared.config import settings


class _FakeClient:
    """Returns a canned httpx.Response for every request."""

    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {}
        self.requests: list[str] = []

    async def post(self, url, **kwargs):
        self.requests.append(url)
        req = httpx.Request("POST", url)
        return httpx.Response(self.status, request=req, json=self.payload)

    async def get(self, url, **kwargs):
        self.requests.append(url)
        req = httpx.Request("GET", url)
        return httpx.Response(self.status, request=req, json=self.payload)


class _ConnectErrorClient:
    async def post(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    # validate_url resolves DNS — keep the suite offline.
    monkeypatch.setattr(browser, "validate_url", lambda url: url)


@pytest.fixture()
def _reset_blank_key_log():
    browser._blank_key_logged = False
    yield
    browser._blank_key_logged = False


class TestBlankKeyIsLoud:
    def test_blank_key_logs_one_error_and_sends_no_placeholder(
        self, monkeypatch, caplog, _reset_blank_key_log
    ):
        monkeypatch.setattr(settings, "BROWSER_WORKER_API_KEY", "")
        with caplog.at_level(logging.ERROR, logger="shared.tools.browser"):
            headers = browser._worker_headers()
            browser._worker_headers()  # second call must not re-log

        assert headers["X-API-Key"] == ""  # no fake "internal" placeholder
        errors = [
            r for r in caplog.records if "BROWSER_WORKER_API_KEY" in r.message
        ]
        assert len(errors) == 1

    def test_configured_key_is_sent_without_noise(
        self, monkeypatch, caplog, _reset_blank_key_log
    ):
        monkeypatch.setattr(settings, "BROWSER_WORKER_API_KEY", "k-1")
        with caplog.at_level(logging.ERROR, logger="shared.tools.browser"):
            headers = browser._worker_headers()
        assert headers == {"X-API-Key": "k-1"}
        assert caplog.records == []


class TestAuthErrorsNeverFallBack:
    def _wire(self, monkeypatch, client):
        monkeypatch.setattr(browser, "_get_http_client", lambda: client)

        async def direct_must_not_run(url):
            raise AssertionError(
                "401/403 must not fall back to direct unguarded HTTP"
            )

        monkeypatch.setattr(browser, "_direct_fetch", direct_must_not_run)

    @pytest.mark.parametrize("status", [401, 403])
    def test_extract_page_raises_on_auth_rejection(self, monkeypatch, status):
        self._wire(monkeypatch, _FakeClient(status=status))
        with pytest.raises(browser.BrowserWorkerAuthError):
            asyncio.run(browser.extract_page("https://example.com"))

    def test_scrape_product_images_raises_on_auth_rejection(self, monkeypatch):
        self._wire(monkeypatch, _FakeClient(status=401))
        with pytest.raises(browser.BrowserWorkerAuthError):
            asyncio.run(browser.scrape_product_images("https://example.com"))

    def test_crawl_site_raises_on_auth_rejection(self, monkeypatch):
        self._wire(monkeypatch, _FakeClient(status=403))
        with pytest.raises(browser.BrowserWorkerAuthError):
            asyncio.run(browser.crawl_site("https://example.com"))

    def test_take_screenshot_raises_on_auth_rejection(self, monkeypatch):
        self._wire(monkeypatch, _FakeClient(status=401))
        with pytest.raises(browser.BrowserWorkerAuthError):
            asyncio.run(browser.take_screenshot("https://example.com"))


class TestGenuineUnavailabilityStillFallsBack:
    def test_connect_error_falls_back_to_direct_fetch(self, monkeypatch):
        monkeypatch.setattr(
            browser, "_get_http_client", lambda: _ConnectErrorClient()
        )
        fallback_page = {"url": "https://example.com", "title": "t", "text": "x"}

        async def fake_direct(url):
            return fallback_page

        monkeypatch.setattr(browser, "_direct_fetch", fake_direct)
        out = asyncio.run(browser.extract_page("https://example.com"))
        assert out == fallback_page

    def test_worker_503_falls_back_to_direct_fetch(self, monkeypatch):
        # 5xx is unavailability, not misconfiguration — the fallback stays.
        monkeypatch.setattr(
            browser, "_get_http_client", lambda: _FakeClient(status=503)
        )
        fallback_page = {"url": "https://example.com", "title": "t", "text": "x"}

        async def fake_direct(url):
            return fallback_page

        monkeypatch.setattr(browser, "_direct_fetch", fake_direct)
        out = asyncio.run(browser.extract_page("https://example.com"))
        assert out == fallback_page
