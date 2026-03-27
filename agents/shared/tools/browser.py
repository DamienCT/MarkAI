"""Browser-worker client with direct HTTP fallback.

Tries the browser-worker microservice first. If unavailable, falls back to
direct HTTP fetch with basic HTML parsing — enough for research context."""

from __future__ import annotations

import logging
import re
from typing import Any
from html.parser import HTMLParser

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)


class _TextExtractor(HTMLParser):
    """Minimal HTML parser that extracts text, title, meta description, and links."""
    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self.title = ""
        self.description = ""
        self.links: list[str] = []
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
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarkAI Research Bot/1.0)",
            "Accept": "text/html",
        })
        resp.raise_for_status()
        html = resp.text

    parser = _TextExtractor()
    parser.feed(html)

    # Clean and truncate text
    full_text = " ".join(parser.text_parts)
    # Remove excessive whitespace
    full_text = re.sub(r'\s+', ' ', full_text).strip()

    return {
        "url": url,
        "title": parser.title,
        "description": parser.description,
        "text": full_text[:5000],
        "links": parser.links[:30],
    }


async def take_screenshot(url: str, full_page: bool = True) -> bytes:
    """Capture a screenshot via browser-worker."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/screenshot",
            json={"url": url, "fullPage": full_page},
        )
        resp.raise_for_status()
        return resp.content


async def extract_page(url: str) -> dict[str, Any]:
    """Extract structured content from a URL. Falls back to direct HTTP if browser-worker is down."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.BROWSER_WORKER_URL}/extract",
                json={"url": url},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.info("Browser-worker unavailable, using direct HTTP for %s", url)
        try:
            return await _direct_fetch(url)
        except Exception as exc:
            logger.warning("Direct fetch also failed for %s: %s", url, exc)
            return {"url": url, "title": "", "text": "", "error": str(exc)}


async def scrape_product_images(url: str) -> list[str]:
    """Scrape product image URLs from the given page."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/scrape-images",
            json={"url": url},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("images", [])


async def crawl_site(url: str, max_pages: int = 20) -> list[dict[str, Any]]:
    """Crawl a website. Falls back to direct HTTP fetch of the homepage if browser-worker is down."""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{settings.BROWSER_WORKER_URL}/crawl",
                json={"url": url, "maxPages": max_pages},
            )
            resp.raise_for_status()
            return resp.json().get("pages", [])
    except Exception:
        logger.info("Browser-worker unavailable, fetching %s directly", url)
        try:
            page = await _direct_fetch(url)
            return [page] if page.get("text") else []
        except Exception as exc:
            logger.warning("Direct crawl failed for %s: %s", url, exc)
            return []
