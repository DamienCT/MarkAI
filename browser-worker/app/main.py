from __future__ import annotations

import hmac
import logging
import urllib.parse
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException
from playwright.async_api import Browser, async_playwright
from pydantic import BaseModel, HttpUrl

from app.capture import extract_page, take_screenshot
from app.config import settings
from app.url_guard import URLGuardError, host_matches, validate_url
from app.product_image import (
    search_supplier_website,
    web_search_logo,
    web_search_product_image,
)
from app.social_scraper import (
    scrape_facebook_page,
    scrape_instagram_profile,
    scrape_linkedin_company,
)

logger = logging.getLogger("browser-worker")


def _anon_allowed() -> bool:
    """The dev escape hatch never applies in production (fail closed)."""
    return settings.BROWSER_WORKER_ALLOW_ANON and settings.MARKAI_ENV != "production"


async def verify_api_key(x_api_key: str = Header("", alias="X-API-Key")) -> str:
    """Validate the API key from the X-API-Key header (fail closed on blank)."""
    if not settings.BROWSER_WORKER_API_KEY:
        if _anon_allowed():
            return x_api_key
        raise HTTPException(
            status_code=503,
            detail=(
                "BROWSER_WORKER_API_KEY is not configured; refusing all requests. "
                "Set the key, or BROWSER_WORKER_ALLOW_ANON=true for local dev only."
            ),
        )
    if not hmac.compare_digest(
        x_api_key.encode("utf-8"), settings.BROWSER_WORKER_API_KEY.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


async def _guard_target_url(url: str) -> None:
    """Reject SSRF targets (private/metadata/odd-port/etc.) with a 400."""
    try:
        await validate_url(url)
    except URLGuardError as exc:
        raise HTTPException(status_code=400, detail=f"URL refused: {exc}") from exc

# Shared browser instance, set during lifespan
_browser: Browser | None = None
_playwright_ctx = None


def get_browser() -> Browser:
    if _browser is None:
        raise RuntimeError("Browser not initialized")
    return _browser


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _browser, _playwright_ctx
    if not settings.BROWSER_WORKER_API_KEY:
        if _anon_allowed():
            logger.critical(
                "BROWSER_WORKER_API_KEY is blank and BROWSER_WORKER_ALLOW_ANON=true — "
                "running UNAUTHENTICATED. Local development only; never in production."
            )
        else:
            logger.critical(
                "BROWSER_WORKER_API_KEY is not set — all /capture requests will be "
                "refused (503) until a key is configured "
                "(the ALLOW_ANON escape hatch is inert in production)."
            )
    logger.info("Launching Playwright Chromium...")
    _playwright_ctx = await async_playwright().start()
    _browser = await _playwright_ctx.chromium.launch(headless=True)
    logger.info("Chromium browser ready")
    yield
    logger.info("Shutting down browser...")
    if _browser:
        await _browser.close()
    if _playwright_ctx:
        await _playwright_ctx.stop()
    logger.info("Browser shut down")


app = FastAPI(
    title="MARKAI Browser Worker",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Request / Response Models ──────────────────────────────────────


class ScreenshotRequest(BaseModel):
    url: HttpUrl


class ScreenshotResponse(BaseModel):
    screenshot_url: str
    width: int
    height: int


class ExtractRequest(BaseModel):
    url: HttpUrl


class ExtractResponse(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    og_image: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    text_content: str = ""


class ProductImageRequest(BaseModel):
    product_name: str
    vendor_name: str


class ProductImageResponse(BaseModel):
    image_url: str | None = None
    source: str | None = None
    total: int | None = None


class LogoRequest(BaseModel):
    vendor_name: str
    offset: int = 0


class SocialPageRequest(BaseModel):
    url: HttpUrl


class SocialPageResponse(BaseModel):
    platform: str
    data: dict


# ── Endpoints ──────────────────────────────────────────────────────


@app.post("/capture/screenshot", response_model=ScreenshotResponse, dependencies=[Depends(verify_api_key)])
async def capture_screenshot(req: ScreenshotRequest):
    await _guard_target_url(str(req.url))
    try:
        result = await take_screenshot(get_browser(), str(req.url))
        return result
    except Exception as exc:
        logger.exception("Screenshot capture failed for %s", req.url)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/extract", response_model=ExtractResponse, dependencies=[Depends(verify_api_key)])
async def capture_extract(req: ExtractRequest):
    await _guard_target_url(str(req.url))
    try:
        result = await extract_page(get_browser(), str(req.url))
        return result
    except Exception as exc:
        logger.exception("Page extraction failed for %s", req.url)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/product-image", response_model=ProductImageResponse, dependencies=[Depends(verify_api_key)])
async def capture_product_image(req: ProductImageRequest):
    try:
        # First try direct supplier website search
        result = await search_supplier_website(
            get_browser(), req.vendor_name, req.product_name
        )
        if result and result.get("image_url"):
            return result

        # Fall back to general web search
        result = await web_search_product_image(
            get_browser(), f"{req.vendor_name} {req.product_name}"
        )
        return result
    except Exception as exc:
        logger.exception(
            "Product image search failed for %s %s",
            req.vendor_name,
            req.product_name,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/logo", response_model=ProductImageResponse, dependencies=[Depends(verify_api_key)])
async def capture_logo(req: LogoRequest):
    """Find a brand/manufacturer logo via Bing image search. Biases the query
    toward a transparent PNG. ``offset`` cycles through alternative candidates
    so the caller can request a different logo without an editable query."""
    vendor = (req.vendor_name or "").strip()
    if not vendor:
        return {"image_url": None, "source": None, "total": 0}
    try:
        return await web_search_logo(get_browser(), vendor, req.offset)
    except Exception as exc:
        logger.exception("Logo search failed for %s", vendor)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/social-page", response_model=SocialPageResponse, dependencies=[Depends(verify_api_key)])
async def capture_social_page(req: SocialPageRequest):
    url_str = str(req.url)
    await _guard_target_url(url_str)
    # Exact-host / dot-suffix matching — substring matching let e.g.
    # "evil.example/?x=instagram.com" pick a scraper for an arbitrary URL.
    host = urllib.parse.urlsplit(url_str).hostname
    try:
        if host_matches(host, "instagram.com"):
            data = await scrape_instagram_profile(get_browser(), url_str)
            return SocialPageResponse(platform="instagram", data=data)
        elif host_matches(host, "facebook.com") or host_matches(host, "fb.com"):
            data = await scrape_facebook_page(get_browser(), url_str)
            return SocialPageResponse(platform="facebook", data=data)
        elif host_matches(host, "linkedin.com"):
            data = await scrape_linkedin_company(get_browser(), url_str)
            return SocialPageResponse(platform="linkedin", data=data)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported social platform URL: {url_str}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Social page scrape failed for %s", url_str)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def health():
    browser_ok = _browser is not None and _browser.is_connected()
    return {
        "status": "healthy" if browser_ok else "degraded",
        "browser_connected": browser_ok,
    }
