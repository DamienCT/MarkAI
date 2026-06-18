from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException
from playwright.async_api import Browser, async_playwright
from pydantic import BaseModel, HttpUrl

from app.capture import extract_page, take_screenshot
from app.config import settings
from app.product_image import search_supplier_website, web_search_product_image
from app.social_scraper import (
    scrape_facebook_page,
    scrape_instagram_profile,
    scrape_linkedin_company,
)

logger = logging.getLogger("browser-worker")


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """Validate the API key from the X-API-Key header."""
    if not settings.BROWSER_WORKER_API_KEY:
        # No key configured — allow (dev mode)
        return x_api_key
    if x_api_key != settings.BROWSER_WORKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

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


class LogoRequest(BaseModel):
    vendor_name: str


class SocialPageRequest(BaseModel):
    url: HttpUrl


class SocialPageResponse(BaseModel):
    platform: str
    data: dict


# ── Endpoints ──────────────────────────────────────────────────────


@app.post("/capture/screenshot", response_model=ScreenshotResponse, dependencies=[Depends(verify_api_key)])
async def capture_screenshot(req: ScreenshotRequest):
    try:
        result = await take_screenshot(get_browser(), str(req.url))
        return result
    except Exception as exc:
        logger.exception("Screenshot capture failed for %s", req.url)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/extract", response_model=ExtractResponse, dependencies=[Depends(verify_api_key)])
async def capture_extract(req: ExtractRequest):
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
    """Find a brand/manufacturer logo via Bing image search (fallback when
    Brandfetch is unavailable). Biases the query toward a transparent PNG."""
    vendor = (req.vendor_name or "").strip()
    if not vendor:
        return {"image_url": None, "source": None}
    try:
        result = await web_search_product_image(
            get_browser(), f'"{vendor}" logo png transparent'
        )
        if not (result and result.get("image_url")):
            result = await web_search_product_image(get_browser(), f"{vendor} logo")
        return result
    except Exception as exc:
        logger.exception("Logo search failed for %s", vendor)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/capture/social-page", response_model=SocialPageResponse, dependencies=[Depends(verify_api_key)])
async def capture_social_page(req: SocialPageRequest):
    url_str = str(req.url)
    try:
        if "instagram.com" in url_str:
            data = await scrape_instagram_profile(get_browser(), url_str)
            return SocialPageResponse(platform="instagram", data=data)
        elif "facebook.com" in url_str:
            data = await scrape_facebook_page(get_browser(), url_str)
            return SocialPageResponse(platform="facebook", data=data)
        elif "linkedin.com" in url_str:
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
