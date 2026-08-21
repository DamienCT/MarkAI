"""Browser-worker client with direct HTTP fallback.

Tries the browser-worker microservice first. If unavailable, falls back to
direct HTTP fetch with basic HTML parsing — enough for research context.

Function → browser-worker route map:
    take_screenshot        → POST /capture/screenshot (then downloads the PNG
                             from the MinIO URL the worker returns)
    extract_page           → POST /capture/extract
    scrape_product_images  → POST /capture/extract (og_image; the worker has
                             no bulk image-scrape route — remaining <img> URLs
                             come from a direct HTML fetch)
    crawl_site             → POST /capture/extract once per page (the worker
                             has no /crawl route; links are discovered via a
                             direct HTML fetch of the start page)

Every worker call sends the required ``X-API-Key`` header, sourced from
``settings.BROWSER_WORKER_API_KEY``. A blank key is a deployment
misconfiguration: it is logged as an ERROR (once) and the worker will refuse
the request. A 401/403 from the worker NEVER falls back to direct unguarded
HTTP — that would silently bypass the worker's SSRF guards — it raises
``BrowserWorkerAuthError`` instead. Genuine unavailability (connect error,
timeout, 5xx) keeps the direct-fetch fallback."""

from __future__ import annotations

import logging
import re
from typing import Any
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from shared.config import settings
from shared.url_validator import validate_url

logger = logging.getLogger(__name__)

# ── Shared httpx client (lazy singleton) ────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_connections=20),
            follow_redirects=True,
        )
    return _http_client


class BrowserWorkerAuthError(RuntimeError):
    """The browser-worker rejected our credentials (401/403).

    Configuration problem, not availability: falling back to direct HTTP here
    would silently bypass the worker's SSRF/auth guards, so callers get this
    raised at them instead."""


_blank_key_logged = False


def _worker_headers() -> dict[str, str]:
    """Auth header for the browser-worker (required on every /capture route)."""
    global _blank_key_logged
    key = settings.BROWSER_WORKER_API_KEY
    if not key and not _blank_key_logged:
        _blank_key_logged = True
        logger.error(
            "BROWSER_WORKER_API_KEY is blank — the browser-worker refuses "
            "unauthenticated requests. Set BROWSER_WORKER_API_KEY in .env "
            "(same value the browser-worker container is started with)."
        )
    return {"X-API-Key": key}


def _raise_on_auth_error(exc: Exception, url: str) -> None:
    """Convert a worker 401/403 into a loud, non-fallback failure."""
    if (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (401, 403)
    ):
        logger.error(
            "browser-worker rejected credentials (%s) for %s — "
            "BROWSER_WORKER_API_KEY is misconfigured; refusing to fall back "
            "to direct unguarded HTTP.",
            exc.response.status_code,
            url,
        )
        raise BrowserWorkerAuthError(
            f"browser-worker auth misconfigured "
            f"({exc.response.status_code}): check BROWSER_WORKER_API_KEY"
        ) from exc


async def _worker_extract(url: str) -> dict[str, Any]:
    """POST /capture/extract on the browser-worker and normalize the response.

    The worker returns ``{url, title, description, og_image, og_title,
    og_description, text_content}``; a ``text`` alias is added so worker and
    direct-fetch results share the same shape."""
    client = _get_http_client()
    resp = await client.post(
        f"{settings.BROWSER_WORKER_URL}/capture/extract",
        json={"url": url},
        headers=_worker_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    data.setdefault("text", (data.get("text_content") or "")[:5000])
    return data


class _TextExtractor(HTMLParser):
    """Minimal HTML parser that extracts text, title, meta description, links, and images."""

    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self.title = ""
        self.description = ""
        self.links: list[str] = []
        self.images: list[str] = []
        self._in_title = False
        self._skip_tags = {"script", "style", "noscript", "svg"}
        self._current_skip = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in self._skip_tags:
            self._current_skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            if attrs_dict.get("name", "").lower() == "description":
                self.description = attrs_dict.get("content", "")
        if tag == "a" and attrs_dict.get("href", "").startswith("http"):
            self.links.append(attrs_dict["href"])
        if tag == "img":
            src = attrs_dict.get("src") or attrs_dict.get("data-src") or ""
            if src and not src.startswith("data:"):
                self.images.append(src)

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._current_skip = max(0, self._current_skip - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        if self._current_skip == 0:
            text = data.strip()
            if text and len(text) > 2:
                self.text_parts.append(text)


async def _direct_fetch(url: str) -> dict[str, Any]:
    """Fetch a URL directly via HTTP and extract basic content."""
    validate_url(url)
    client = _get_http_client()
    resp = await client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarkAI Research Bot/1.0)",
            "Accept": "text/html",
        },
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.text

    parser = _TextExtractor()
    parser.feed(html)

    # Clean and truncate text
    full_text = " ".join(parser.text_parts)
    # Remove excessive whitespace
    full_text = re.sub(r"\s+", " ", full_text).strip()

    # Resolve image srcs against the page URL and dedupe
    images: list[str] = []
    for src in parser.images:
        resolved = urljoin(url, src)
        if resolved.startswith("http") and resolved not in images:
            images.append(resolved)

    return {
        "url": url,
        "title": parser.title,
        "description": parser.description,
        "text": full_text[:5000],
        "links": parser.links[:30],
        "images": images[:20],
    }


def _same_domain_links(base_url: str, links: list[str]) -> list[str]:
    """Filter *links* to unique same-domain URLs, excluding *base_url* itself."""
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        clean = link.split("#", 1)[0].rstrip("/")
        if not clean or clean == base_url.rstrip("/") or clean in seen:
            continue
        host = urlparse(clean).netloc.lower().removeprefix("www.")
        if host != base_host:
            continue
        seen.add(clean)
        result.append(clean)
    return result


async def take_screenshot(url: str, full_page: bool = True) -> bytes:
    """Capture a screenshot via browser-worker (POST /capture/screenshot).

    The worker uploads the PNG to MinIO and returns its URL, so the bytes are
    downloaded here to keep this function's contract. ``full_page`` is kept for
    signature compatibility — the worker decides via its own config."""
    validate_url(url)
    client = _get_http_client()
    resp = await client.post(
        f"{settings.BROWSER_WORKER_URL}/capture/screenshot",
        json={"url": url},
        headers=_worker_headers(),
        timeout=60,
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_on_auth_error(exc, url)
        raise
    screenshot_url = (resp.json() or {}).get("screenshot_url")
    if not screenshot_url:
        raise RuntimeError(f"browser-worker returned no screenshot_url for {url}")
    # The URL points at private MinIO (http://minio:9000/{bucket}/{object});
    # buckets have no anonymous read policy, so fetch via the authenticated
    # MinIO client instead of a raw (403-bound) HTTP GET.
    from urllib.parse import urlparse

    from shared.tools.storage import async_download_file

    path = urlparse(screenshot_url).path.lstrip("/")
    bucket, _, object_name = path.partition("/")
    if not bucket or not object_name:
        raise RuntimeError(f"Unparseable screenshot_url from browser-worker: {screenshot_url}")
    return await async_download_file(bucket, object_name)


async def extract_page(url: str) -> dict[str, Any]:
    """Extract structured content via browser-worker (POST /capture/extract).

    Falls back to direct HTTP if browser-worker is down."""
    validate_url(url)
    try:
        return await _worker_extract(url)
    except Exception as exc:
        _raise_on_auth_error(exc, url)
        logger.warning(
            "Browser-worker extract failed for %s (%s); falling back to direct HTTP",
            url,
            exc,
        )
        try:
            return await _direct_fetch(url)
        except Exception as exc:
            logger.warning("Direct fetch also failed for %s: %s", url, exc)
            return {"url": url, "title": "", "text": "", "error": str(exc)}


async def scrape_product_images(url: str) -> list[str]:
    """Scrape product image URLs from the given page.

    Worker route: POST /capture/extract — the worker has no bulk image-scrape
    endpoint, so the JS-rendered ``og_image`` is used when present; otherwise
    a direct HTML fetch collects <img> URLs from the page."""
    validate_url(url)
    try:
        data = await _worker_extract(url)
        og_image = data.get("og_image")
        if og_image:
            return [og_image]
    except Exception as exc:
        _raise_on_auth_error(exc, url)
        logger.warning(
            "Browser-worker extract failed for %s (%s); falling back to direct HTTP for images",
            url,
            exc,
        )
    try:
        page = await _direct_fetch(url)
        return page.get("images", [])
    except Exception as exc:
        logger.warning("Direct image fetch failed for %s: %s", url, exc)
        return []


async def crawl_site(url: str, max_pages: int = 20) -> list[dict[str, Any]]:
    """Crawl a website through the browser-worker.

    Worker route: POST /capture/extract, called once per page — the worker has
    no /crawl endpoint. Same-domain links are discovered with a direct HTML
    fetch of the start page (the worker's extract response carries no links),
    then each page is rendered through the worker. Falls back to a direct HTTP
    fetch of the start page if the browser-worker is down."""
    validate_url(url)
    try:
        pages: list[dict[str, Any]] = [await _worker_extract(url)]
    except Exception as exc:
        _raise_on_auth_error(exc, url)
        logger.warning(
            "Browser-worker unavailable for crawl of %s (%s); fetching directly",
            url,
            exc,
        )
        try:
            page = await _direct_fetch(url)
            return [page] if page.get("text") else []
        except Exception as exc:
            logger.warning("Direct crawl failed for %s: %s", url, exc)
            return []

    # Discover same-domain links via direct fetch (worker extract has no links)
    links: list[str] = []
    try:
        seed = await _direct_fetch(url)
        links = _same_domain_links(url, seed.get("links", []))
    except Exception as exc:
        logger.debug("Link discovery failed for %s: %s", url, exc)

    for link in links[: max(0, max_pages - 1)]:
        try:
            validate_url(link)
            pages.append(await _worker_extract(link))
        except Exception as exc:
            logger.debug("Failed to extract %s during crawl: %s", link, exc)

    return pages
