"""Product image discovery via Bing Images + Playwright.

Searches Bing's image index (more permissive to headless browsers than
Google), parses the JSON-encoded result metadata, then validates each
candidate URL with a real HTTP fetch before returning it. The caller
gets a single image URL that is guaranteed to be reachable, the right
content type, and a sane size.
"""

from __future__ import annotations

import logging
import urllib.parse

import httpx
from playwright.async_api import Browser

from app.config import settings

logger = logging.getLogger("browser-worker.product_image")


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_DOWNLOAD_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Image acceptance thresholds — large enough to be a real product photo,
# small enough that the downstream MinIO upload + Gemini swap don't choke.
_MIN_IMAGE_BYTES = 10_000
_MAX_IMAGE_BYTES = 10_000_000


async def _search_bing_images(
    browser: Browser, query: str, max_results: int = 12
) -> list[str]:
    """Return candidate image URLs from a Bing Images search.

    Bing embeds each result as JSON inside the ``m`` attribute of
    ``<a class="iusc">``. That structure is far more stable than Google's
    frequently-rewritten markup, which is why the previous Google-based
    selectors started returning nothing in production.
    """
    encoded = urllib.parse.quote_plus(query)
    search_url = (
        f"https://www.bing.com/images/search?q={encoded}&form=HDRSC2&first=1"
    )

    context = await browser.new_context(
        user_agent=_BROWSER_UA,
        viewport={"width": 1366, "height": 768},
        locale="en-US",
    )
    page = await context.new_page()
    try:
        await page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=settings.PAGE_TIMEOUT_MS,
        )
        urls = await page.evaluate(
            """(maxN) => {
                const out = [];
                for (const a of document.querySelectorAll('a.iusc')) {
                    const m = a.getAttribute('m');
                    if (!m) continue;
                    try {
                        const meta = JSON.parse(m);
                        if (meta && meta.murl && meta.murl.startsWith('http')) {
                            out.push(meta.murl);
                        }
                    } catch (e) {}
                    if (out.length >= maxN) break;
                }
                return out;
            }""",
            max_results,
        )
        return [u for u in (urls or []) if isinstance(u, str)]
    except Exception:
        logger.exception("Bing image search failed for query=%r", query)
        return []
    finally:
        await page.close()
        await context.close()


async def _validate_image_url(url: str) -> bool:
    """Fetch *url* and confirm it returns a real, sizeable image.

    Returning False on any failure lets the caller move on to the next
    candidate without aborting the whole search.
    """
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_DOWNLOAD_HEADERS
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return False
        ct = resp.headers.get("content-type", "").lower()
        if not any(t in ct for t in ("image/jpeg", "image/png", "image/webp")):
            return False
        return _MIN_IMAGE_BYTES < len(resp.content) <= _MAX_IMAGE_BYTES
    except Exception:
        return False


async def _first_downloadable(browser: Browser, query: str) -> str | None:
    """Run a Bing search and return the first candidate URL that downloads."""
    for url in await _search_bing_images(browser, query):
        if await _validate_image_url(url):
            return url
    return None


async def search_supplier_website(
    browser: Browser,
    vendor_name: str,
    product_name: str,
) -> dict:
    """Look for a real product photo, biasing the search toward the vendor.

    Tries progressively more permissive queries — vendor-quoted first so we
    favour the actual brand, then plain vendor+product, then product alone.
    Each candidate URL is validated by a real download before being returned
    so the caller never gets a 404 / hotlink-blocked image.
    """
    vendor = (vendor_name or "").strip()
    product = (product_name or "").strip()
    if not product:
        return {"image_url": None, "source": None}

    queries: list[str] = []
    if vendor:
        queries.append(f'"{vendor}" {product}')
        queries.append(f"{vendor} {product} product photo")
    queries.append(f"{product} product photo")
    queries.append(product)

    for query in queries:
        url = await _first_downloadable(browser, query)
        if url:
            logger.info(
                "Found product image for vendor=%r product=%r via query=%r: %s",
                vendor,
                product,
                query,
                url[:120],
            )
            return {"image_url": url, "source": "bing_images"}

    logger.info(
        "No downloadable product image found for vendor=%r product=%r",
        vendor,
        product,
    )
    return {"image_url": None, "source": None}


async def web_search_product_image(browser: Browser, query: str) -> dict:
    """Open-web image search — same Bing path, kept for API compatibility."""
    url = await _first_downloadable(browser, query.strip())
    if url:
        return {"image_url": url, "source": "bing_images"}
    return {"image_url": None, "source": None}


async def web_search_logo(
    browser: Browser, vendor: str, offset: int = 0
) -> dict:
    """Find a manufacturer/vendor logo, returning the candidate at *offset*.

    Validates several Bing candidates up front so the caller can cycle through
    alternatives ("new search" button) by incrementing *offset* — without an
    editable query. ``total`` reports how many valid candidates were found so
    the offset can wrap cleanly.
    """
    vendor = (vendor or "").strip()
    if not vendor:
        return {"image_url": None, "source": None, "total": 0}

    candidates: list[str] = []
    seen: set[str] = set()
    for query in (f'"{vendor}" logo png transparent', f"{vendor} logo"):
        for url in await _search_bing_images(browser, query):
            if url in seen:
                continue
            seen.add(url)
            if await _validate_image_url(url):
                candidates.append(url)
            if len(candidates) >= 6:
                break
        if len(candidates) >= 6:
            break

    if not candidates:
        logger.info("No downloadable logo found for vendor=%r", vendor)
        return {"image_url": None, "source": None, "total": 0}

    chosen = candidates[offset % len(candidates)]
    return {
        "image_url": chosen,
        "source": "bing_images",
        "total": len(candidates),
    }
