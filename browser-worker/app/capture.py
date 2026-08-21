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
from app.url_guard import EXTRACT_MAX_BYTES, install_page_guard

logger = logging.getLogger("browser-worker.capture")

# Server-side caps on what an extraction can hand back to callers — the
# in-page JS truncates too, but the page controls that script's inputs.
_MAX_META_CHARS = 10_000
_MAX_TEXT_CHARS = 50_000


def _cap(value: str | None, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:limit]


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
    # Dedicated context with service workers blocked: SW-initiated requests
    # bypass Playwright route interception, so a hostile page could register
    # one for blind SSRF past the URL guard (default-context new_page() can't
    # set this).
    context = await browser.new_context(service_workers="block")
    page = await context.new_page()
    try:
        await install_page_guard(page)
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
        await context.close()


async def extract_page(browser: Browser, url: str) -> dict:
    """Navigate to *url* and extract structured metadata + text content."""
    # Service workers blocked — same blind-SSRF rationale as take_screenshot.
    context = await browser.new_context(service_workers="block")
    page = await context.new_page()
    try:
        await install_page_guard(page)
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

        text = (text_content or "").strip()[:_MAX_TEXT_CHARS]
        # Belt-and-braces: the whole readable payload stays under the guard's
        # 2 MB extract cap even if every field is at its limit.
        if len(text.encode("utf-8", errors="ignore")) > EXTRACT_MAX_BYTES:
            text = text.encode("utf-8", errors="ignore")[:EXTRACT_MAX_BYTES].decode(
                "utf-8", errors="ignore"
            )
        return {
            "url": url,
            "title": _cap(title, _MAX_META_CHARS),
            "description": _cap(description, _MAX_META_CHARS),
            "og_image": _cap(og_image, _MAX_META_CHARS),
            "og_title": _cap(og_title, _MAX_META_CHARS),
            "og_description": _cap(og_description, _MAX_META_CHARS),
            "text_content": text,
        }
    finally:
        await context.close()
