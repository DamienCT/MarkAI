"""Product image discovery via real Playwright browsing + BeautifulSoup.

Searches supplier websites and the open web for product images.
"""

from __future__ import annotations

import logging
import urllib.parse

from bs4 import BeautifulSoup
from playwright.async_api import Browser

from app.config import settings

logger = logging.getLogger("browser-worker.product_image")


async def search_supplier_website(
    browser: Browser,
    vendor_name: str,
    product_name: str,
) -> dict:
    """Google-search for *product_name* on the vendor's website, navigate to
    the top result, and extract the best product image URL.

    Returns dict with image_url and source, or empty image_url if not found.
    """
    query = urllib.parse.quote_plus(f"site:{vendor_name}.com {product_name}")
    search_url = f"https://www.google.com/search?q={query}&tbm=isch"

    page = await browser.new_page()
    try:
        await page.goto(
            search_url, wait_until="domcontentloaded", timeout=settings.PAGE_TIMEOUT_MS
        )

        # Try to get the first organic search result link
        first_link = await page.evaluate(
            """() => {
                // Google image results put URLs in anchor tags
                const anchors = document.querySelectorAll('a[href*="imgurl="]');
                if (anchors.length > 0) {
                    const href = anchors[0].getAttribute('href');
                    const match = href.match(/imgurl=([^&]+)/);
                    return match ? decodeURIComponent(match[1]) : null;
                }
                // Fallback: try thumbnail images
                const imgs = document.querySelectorAll('img[src^="http"]');
                for (const img of imgs) {
                    const src = img.getAttribute('src');
                    if (src && !src.includes('google') && !src.includes('gstatic')) {
                        return src;
                    }
                }
                return null;
            }"""
        )

        if first_link:
            return {"image_url": first_link, "source": "google_image_search"}

        # Fallback: navigate to the vendor site directly and look for product
        vendor_search_url = f"https://www.{vendor_name.lower().replace(' ', '')}.com/search?q={urllib.parse.quote_plus(product_name)}"
        await page.goto(
            vendor_search_url,
            wait_until="domcontentloaded",
            timeout=settings.PAGE_TIMEOUT_MS,
        )

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Look for product images via common patterns
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            alt = (img.get("alt") or "").lower()
            if product_name.lower().split()[0] in alt and src.startswith("http"):
                return {"image_url": src, "source": f"{vendor_name}_website"}

        # Check og:image as last resort
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            return {"image_url": og_img["content"], "source": f"{vendor_name}_og_image"}

        return {"image_url": None, "source": None}

    except Exception:
        logger.exception(
            "Supplier website search failed for vendor=%s product=%s",
            vendor_name,
            product_name,
        )
        return {"image_url": None, "source": None}
    finally:
        await page.close()


async def web_search_product_image(browser: Browser, query: str) -> dict:
    """Search the open web for a product image matching *query*.

    Returns dict with image_url and source, or empty image_url if not found.
    """
    encoded_query = urllib.parse.quote_plus(f"{query} product image")
    search_url = f"https://www.google.com/search?q={encoded_query}&tbm=isch"

    page = await browser.new_page()
    try:
        await page.goto(
            search_url, wait_until="domcontentloaded", timeout=settings.PAGE_TIMEOUT_MS
        )

        image_url = await page.evaluate(
            """() => {
                const anchors = document.querySelectorAll('a[href*="imgurl="]');
                if (anchors.length > 0) {
                    const href = anchors[0].getAttribute('href');
                    const match = href.match(/imgurl=([^&]+)/);
                    return match ? decodeURIComponent(match[1]) : null;
                }
                // Fallback: grab first non-Google image
                const imgs = document.querySelectorAll('img[src^="http"]');
                for (const img of imgs) {
                    const src = img.getAttribute('src');
                    if (src && !src.includes('google') && !src.includes('gstatic')) {
                        return src;
                    }
                }
                return null;
            }"""
        )

        return {
            "image_url": image_url,
            "source": "web_search" if image_url else None,
        }

    except Exception:
        logger.exception("Web image search failed for query=%s", query)
        return {"image_url": None, "source": None}
    finally:
        await page.close()
