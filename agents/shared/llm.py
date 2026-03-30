"""LiteLLM client wrapper.  All LLM calls route through the LiteLLM proxy.

Never import openai directly — every request goes via LITELLM_BASE_URL.
Models are resolved dynamically from the backend's active model selections.
The real OpenAI model ID is passed with "openai/" prefix so LiteLLM routes
it correctly without needing hardcoded model_list entries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)

from shared.config import settings


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return False


_retry_on_transient = retry_if_exception(_is_retryable)

_HEADERS: dict[str, str] = {}

# Cache for active model lookups: {category: (model_id, expiry_timestamp)}
_model_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 300  # 5 minutes

# Fallback defaults used when the backend API is unreachable
_FALLBACK_MODELS: dict[str, str] = {
    "text": "gpt-5.4",
    "text-fast": "gpt-5.4-mini",
    "image": "gpt-image-1.5",
    "embedding": "text-embedding-3-small",
    "tts": "tts-1",
    "stt": "whisper-1",
    "moderation": "omni-moderation-latest",
    "vision": "gpt-5.4",
}


def _auth_headers() -> dict[str, str]:
    if not _HEADERS:
        _HEADERS["Authorization"] = f"Bearer {settings.LITELLM_MASTER_KEY}"
        _HEADERS["Content-Type"] = "application/json"
    return _HEADERS


async def get_model_for_category(category: str) -> str:
    """Look up the active model for a category from the backend API.

    Results are cached for 5 minutes. Falls back to sensible defaults
    if the backend is unreachable.

    Returns the full LiteLLM model string, e.g. "openai/gpt-5.4".
    """
    now = time.time()

    # Check cache
    if category in _model_cache:
        model_id, expiry = _model_cache[category]
        if now < expiry:
            return f"openai/{model_id}"

    # Fetch from backend API
    try:
        backend_url = settings.BACKEND_URL

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/providers/active",
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            active_models: dict[str, str] = data.get("models", {})

            # Cache all returned models
            for slug, model_id in active_models.items():
                _model_cache[slug] = (model_id, now + _CACHE_TTL)

            if category in active_models:
                return f"openai/{active_models[category]}"
    except Exception:
        # Backend unreachable — use cached value if available (even if expired)
        if category in _model_cache:
            model_id, _ = _model_cache[category]
            return f"openai/{model_id}"

    # Ultimate fallback
    fallback = _FALLBACK_MODELS.get(category, "gpt-5.4")
    _model_cache[category] = (fallback, now + _CACHE_TTL)
    return f"openai/{fallback}"


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from LLM output."""
    return re.sub(r'^```\w*\n?|```$', '', text.strip(), flags=re.MULTILINE).strip()


def parse_llm_json(text: str, fallback: Any = None) -> Any:
    """Parse JSON from LLM output, handling markdown fences and common issues.

    Returns the parsed object, or *fallback* if parsing fails.
    """
    cleaned = strip_markdown_fences(text)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON output (length=%d): %s...", len(text), text[:200])
        return fallback


def validate_llm_output(data: Any, required_fields: list[str] | None = None, expect_list: bool = False) -> bool:
    """Validate that LLM output meets basic structural expectations."""
    if expect_list:
        if not isinstance(data, list):
            logger.warning("Expected list from LLM, got %s", type(data).__name__)
            return False
        if required_fields and data:
            missing = [f for f in required_fields if f not in data[0]]
            if missing:
                logger.warning("LLM list items missing fields: %s", missing)
                return False
    elif isinstance(data, dict) and required_fields:
        missing = [f for f in required_fields if f not in data]
        if missing:
            logger.warning("LLM dict missing fields: %s", missing)
            return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=_retry_on_transient,
    reraise=True,
)
async def chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
    category: str = "text",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Send a chat completion request through the LiteLLM proxy and return
    the assistant message content.

    If ``model`` is not provided, the active model for the given ``category``
    is resolved dynamically from the backend.
    """
    if model is None:
        model = await get_model_for_category(category)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.LITELLM_BASE_URL}/v1/chat/completions",
                headers=_auth_headers(),
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?")
    except (httpx.TimeoutException, httpx.HTTPStatusError):
        # Let tenacity retry handle transient errors (429, 5xx, timeouts)
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=_retry_on_transient,
    reraise=True,
)
async def get_embedding(
    text: str,
    model: str | None = None,
    category: str = "embedding",
) -> list[float]:
    """Return an embedding vector for *text* via the LiteLLM proxy."""
    if model is None:
        model = await get_model_for_category(category)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.LITELLM_BASE_URL}/v1/embeddings",
                headers=_auth_headers(),
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?")
    except httpx.TimeoutException:
        raise
    except httpx.HTTPStatusError:
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=_retry_on_transient,
    reraise=True,
)
async def generate_image(
    prompt: str,
    model: str | None = None,
    category: str = "image",
    size: str = "1024x1024",
    n: int = 1,
) -> str:
    """Generate an image via the LiteLLM proxy and return the first image URL or data URI.

    Handles both url and b64_json response formats (gpt-image-1.5 returns b64_json).
    """
    if model is None:
        model = await get_model_for_category(category)

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.LITELLM_BASE_URL}/v1/images/generations",
                headers=_auth_headers(),
                json={
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "n": n,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["data"][0]

            # gpt-image-1.5 and newer return b64_json, older models return url
            if result.get("url"):
                return result["url"]
            elif result.get("b64_json"):
                # Return as data URI — caller can decode if needed
                return f"data:image/png;base64,{result['b64_json']}"
            else:
                raise ValueError("Image generation returned neither url nor b64_json")
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?")
    except httpx.TimeoutException:
        raise
    except httpx.HTTPStatusError:
        raise
