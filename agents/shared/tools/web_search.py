"""Real web search tool using DuckDuckGo HTML search as the primary engine."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


async def web_search(query: str, max_results: int = 10) -> list[SearchResult]:
    """Search the web via DuckDuckGo HTML endpoint and return parsed results."""
    results: list[SearchResult] = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.post(
            _DDG_URL,
            headers=_HEADERS,
            data={"q": query},
        )
        resp.raise_for_status()
        html = resp.text

    # Parse result blocks from the HTML response
    # Each result sits inside <div class="result ..."> blocks
    result_blocks = re.findall(
        r'<div class="links_main links_deep result__body">(.*?)</div>\s*</div>',
        html,
        re.DOTALL,
    )

    if not result_blocks:
        # Fallback: try a broader pattern
        result_blocks = re.findall(
            r'class="result__body">(.*?)</div>\s*</div>',
            html,
            re.DOTALL,
        )

    for block in result_blocks[:max_results]:
        # Extract URL
        url_match = re.search(r'href="([^"]+)"', block)
        url = url_match.group(1) if url_match else ""
        if url.startswith("//duckduckgo.com/l/?uddg="):
            # Decode the redirect URL
            import urllib.parse

            url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])

        # Extract title
        title_match = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
        title = (
            re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        )

        # Extract snippet
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|span|div)',
            block,
            re.DOTALL,
        )
        snippet = (
            re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
            if snippet_match
            else ""
        )

        if url:
            results.append(SearchResult(title=title, url=url, snippet=snippet))

    logger.info("Web search for %r returned %d results", query, len(results))
    return results
