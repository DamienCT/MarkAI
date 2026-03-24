"""Screenshot and page-extraction helpers using Playwright.

All functions operate on a shared Browser instance passed from main.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone

from minio import Minio
from playwright.async_api import Browser

from app.config import settings

logger = logging.getLogger("browser-worker.capture")


def _minio_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def take_screenshot(browser: Browser, url: str) -> dict:
    """Navigate to *url*, take a full-page screenshot, upload to MinIO.

    Returns dict with screenshot_url, width, height.
    """
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=settings.PAGE_TIMEOUT_MS)

        viewport = page.viewport_size or {"width": 1280, "height": 720}
        png_bytes = await page.screenshot(full_page=settings.SCREENSHOT_FULL_PAGE)

        # Upload to MinIO
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        object_name = f"screenshots/{ts}_{uuid.uuid4().hex[:8]}.png"

        client = _minio_client()
        _ensure_bucket(client, settings.MINIO_BUCKET)

        client.put_object(
            settings.MINIO_BUCKET,
            object_name,
            io.BytesIO(png_bytes),
            length=len(png_bytes),
            content_type="image/png",
        )

        screenshot_url = f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}/{object_name}"

        return {
            "screenshot_url": screenshot_url,
            "width": viewport["width"],
            "height": viewport["height"],
        }
    finally:
        await page.close()


async def extract_page(browser: Browser, url: str) -> dict:
    """Navigate to *url* and extract structured metadata + text content."""
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=settings.PAGE_TIMEOUT_MS)

        title = await page.title()

        # Extract meta tags
        description = await page.evaluate(
            """() => {
                const el = document.querySelector('meta[name="description"]');
                return el ? el.getAttribute('content') : null;
            }"""
        )

        og_image = await page.evaluate(
            """() => {
                const el = document.querySelector('meta[property="og:image"]');
                return el ? el.getAttribute('content') : null;
            }"""
        )

        og_title = await page.evaluate(
            """() => {
                const el = document.querySelector('meta[property="og:title"]');
                return el ? el.getAttribute('content') : null;
            }"""
        )

        og_description = await page.evaluate(
            """() => {
                const el = document.querySelector('meta[property="og:description"]');
                return el ? el.getAttribute('content') : null;
            }"""
        )

        # Extract visible text content (truncated to avoid huge payloads)
        text_content = await page.evaluate(
            """() => {
                const body = document.body;
                if (!body) return '';
                // Remove script/style elements from the clone
                const clone = body.cloneNode(true);
                clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());
                return clone.innerText.substring(0, 50000);
            }"""
        )

        return {
            "url": url,
            "title": title,
            "description": description,
            "og_image": og_image,
            "og_title": og_title,
            "og_description": og_description,
            "text_content": text_content.strip() if text_content else "",
        }
    finally:
        await page.close()
