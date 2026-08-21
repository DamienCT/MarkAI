"""Social media page scrapers using real Playwright navigation.

Each function opens a new page, navigates to the social profile URL,
waits for dynamic content, and extracts structured data.
"""

from __future__ import annotations

import logging

from playwright.async_api import Browser

from app.config import settings
from app.url_guard import install_page_guard

logger = logging.getLogger("browser-worker.social_scraper")


async def scrape_instagram_profile(browser: Browser, url: str) -> dict:
    """Navigate to an Instagram profile and extract public data.

    Returns dict with bio, follower_count, following_count, post_count,
    and recent_thumbnails.
    """
    # Dedicated context with service workers blocked — SW-initiated requests
    # bypass route interception (same blind-SSRF rationale as capture.py).
    context = await browser.new_context(
        service_workers="block",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    try:
        await install_page_guard(page)
        await page.goto(url, wait_until="networkidle", timeout=settings.PAGE_TIMEOUT_MS)

        # Wait for profile header to render
        await page.wait_for_selector("header", timeout=10_000)

        data = await page.evaluate(
            """() => {
                const result = {
                    username: null,
                    full_name: null,
                    bio: null,
                    follower_count: null,
                    following_count: null,
                    post_count: null,
                    profile_pic_url: null,
                    recent_thumbnails: [],
                };

                // Extract from meta tags as a reliable source
                const descMeta = document.querySelector('meta[name="description"]');
                if (descMeta) {
                    const desc = descMeta.getAttribute('content') || '';
                    // Instagram description format: "X Followers, Y Following, Z Posts - ..."
                    const parts = desc.match(/([\\d,.KMkm]+)\\s*Followers/i);
                    if (parts) result.follower_count = parts[1];
                    const fol = desc.match(/([\\d,.KMkm]+)\\s*Following/i);
                    if (fol) result.following_count = fol[1];
                    const posts = desc.match(/([\\d,.KMkm]+)\\s*Posts/i);
                    if (posts) result.post_count = posts[1];
                }

                // Title often has the display name
                const title = document.title || '';
                const titleMatch = title.match(/^(.+?)\\s*\\(@(.+?)\\)/);
                if (titleMatch) {
                    result.full_name = titleMatch[1].trim();
                    result.username = titleMatch[2].trim();
                }

                // Bio from the profile section
                const bioSection = document.querySelector('header section > div > span');
                if (bioSection) {
                    result.bio = bioSection.innerText.trim();
                }

                // Profile picture
                const avatar = document.querySelector('header img[alt*="profile"]') ||
                               document.querySelector('header img');
                if (avatar) {
                    result.profile_pic_url = avatar.getAttribute('src');
                }

                // Recent post thumbnails
                const postImgs = document.querySelectorAll('article img[src]');
                postImgs.forEach((img, i) => {
                    if (i < 12) {
                        result.recent_thumbnails.push(img.getAttribute('src'));
                    }
                });

                return result;
            }"""
        )

        return data

    except Exception:
        logger.exception("Instagram scrape failed for %s", url)
        raise
    finally:
        await context.close()


async def scrape_facebook_page(browser: Browser, url: str) -> dict:
    """Navigate to a Facebook page and extract public info.

    Returns dict with page_name, category, about, likes, followers,
    and recent_posts.
    """
    # Dedicated context with service workers blocked — SW-initiated requests
    # bypass route interception (same blind-SSRF rationale as capture.py).
    context = await browser.new_context(
        service_workers="block",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    try:
        await install_page_guard(page)
        await page.goto(url, wait_until="networkidle", timeout=settings.PAGE_TIMEOUT_MS)

        # Wait for main content
        await page.wait_for_selector('[role="main"]', timeout=10_000)

        data = await page.evaluate(
            """() => {
                const result = {
                    page_name: null,
                    category: null,
                    about: null,
                    likes: null,
                    followers: null,
                    website: null,
                    recent_posts: [],
                };

                // Page title
                const h1 = document.querySelector('h1');
                if (h1) result.page_name = h1.innerText.trim();

                // Meta description
                const descMeta = document.querySelector('meta[name="description"]');
                if (descMeta) {
                    result.about = descMeta.getAttribute('content');
                }

                // Look for likes/followers in the page info spans
                const spans = document.querySelectorAll('a[href*="/friends"], a[href*="/followers"], span');
                spans.forEach(span => {
                    const text = span.innerText || '';
                    if (text.includes('like') && /[\\d,.KMkm]+/.test(text)) {
                        result.likes = text.trim();
                    }
                    if (text.includes('follow') && /[\\d,.KMkm]+/.test(text)) {
                        result.followers = text.trim();
                    }
                });

                // Recent posts
                const postContainers = document.querySelectorAll('[data-ad-preview="message"], [dir="auto"]');
                const seen = new Set();
                postContainers.forEach(el => {
                    const text = el.innerText.trim();
                    if (text.length > 20 && text.length < 2000 && !seen.has(text)) {
                        seen.add(text);
                        if (result.recent_posts.length < 5) {
                            result.recent_posts.push(text);
                        }
                    }
                });

                return result;
            }"""
        )

        return data

    except Exception:
        logger.exception("Facebook scrape failed for %s", url)
        raise
    finally:
        await context.close()


async def scrape_linkedin_company(browser: Browser, url: str) -> dict:
    """Navigate to a LinkedIn company page and extract public info.

    Returns dict with company_name, industry, description, employee_count,
    website, and specialties.
    """
    # Dedicated context with service workers blocked — SW-initiated requests
    # bypass route interception (same blind-SSRF rationale as capture.py).
    context = await browser.new_context(
        service_workers="block",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    try:
        await install_page_guard(page)
        await page.goto(url, wait_until="networkidle", timeout=settings.PAGE_TIMEOUT_MS)

        # Wait for page content to render
        await page.wait_for_selector("main", timeout=10_000)

        data = await page.evaluate(
            """() => {
                const result = {
                    company_name: null,
                    tagline: null,
                    industry: null,
                    description: null,
                    employee_count: null,
                    website: null,
                    specialties: [],
                    headquarters: null,
                };

                // Company name from h1
                const h1 = document.querySelector('h1');
                if (h1) result.company_name = h1.innerText.trim();

                // Meta description
                const descMeta = document.querySelector('meta[name="description"]');
                if (descMeta) {
                    result.description = descMeta.getAttribute('content');
                }

                // OG title for tagline
                const ogTitle = document.querySelector('meta[property="og:title"]');
                if (ogTitle) {
                    result.tagline = ogTitle.getAttribute('content');
                }

                // Look for structured data in the about section
                const dtElements = document.querySelectorAll('dt, .org-page-details__definition-term');
                dtElements.forEach(dt => {
                    const label = dt.innerText.trim().toLowerCase();
                    const dd = dt.nextElementSibling;
                    if (!dd) return;
                    const value = dd.innerText.trim();

                    if (label.includes('website')) result.website = value;
                    if (label.includes('industry')) result.industry = value;
                    if (label.includes('company size') || label.includes('employees'))
                        result.employee_count = value;
                    if (label.includes('headquarters')) result.headquarters = value;
                    if (label.includes('specialties')) {
                        result.specialties = value.split(',').map(s => s.trim()).filter(Boolean);
                    }
                });

                return result;
            }"""
        )

        return data

    except Exception:
        logger.exception("LinkedIn scrape failed for %s", url)
        raise
    finally:
        await context.close()
