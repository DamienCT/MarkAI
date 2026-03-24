"""Browser-worker client.  Calls the browser-worker microservice for screenshots,
page extraction, and product image scraping via real HTTP requests."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)


async def take_screenshot(url: str, full_page: bool = True) -> bytes:
    """Capture a screenshot of *url* and return raw PNG bytes."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/screenshot",
            json={"url": url, "fullPage": full_page},
        )
        resp.raise_for_status()
        return resp.content


async def extract_page(url: str) -> dict[str, Any]:
    """Extract structured content from *url* (text, metadata, links, images)."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/extract",
            json={"url": url},
        )
        resp.raise_for_status()
        return resp.json()


async def scrape_product_images(url: str) -> list[str]:
    """Scrape product image URLs from the given page via browser-worker."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/scrape-images",
            json={"url": url},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("images", [])


async def crawl_site(url: str, max_pages: int = 20) -> list[dict[str, Any]]:
    """Crawl a website starting at *url* and return extracted pages."""
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{settings.BROWSER_WORKER_URL}/crawl",
            json={"url": url, "maxPages": max_pages},
        )
        resp.raise_for_status()
        return resp.json().get("pages", [])
