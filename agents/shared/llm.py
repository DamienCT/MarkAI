"""LiteLLM client wrapper.  All LLM calls route through the LiteLLM proxy.

Never import openai directly — every request goes via LITELLM_BASE_URL.
Models are resolved dynamically from the backend's active model selections.
The real OpenAI model ID is passed with "openai/" prefix so LiteLLM routes
it correctly without needing hardcoded model_list entries.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from shared.config import settings

_HEADERS: dict[str, str] = {}

# Cache for active model lookups: {category: (model_id, expiry_timestamp)}
_model_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 300  # 5 minutes

# Fallback defaults used when the backend API is unreachable
_FALLBACK_MODELS: dict[str, str] = {
    "text": "gpt-4o",
    "text-fast": "gpt-4o-mini",
    "image": "dall-e-3",
    "embedding": "text-embedding-3-small",
    "tts": "tts-1",
    "stt": "whisper-1",
    "moderation": "omni-moderation-latest",
    "vision": "gpt-4o",
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

    Returns the full LiteLLM model string, e.g. "openai/gpt-4o".
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
    fallback = _FALLBACK_MODELS.get(category, "gpt-4o")
    _model_cache[category] = (fallback, now + _CACHE_TTL)
    return f"openai/{fallback}"


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


async def get_embedding(
    text: str,
    model: str | None = None,
    category: str = "embedding",
) -> list[float]:
    """Return an embedding vector for *text* via the LiteLLM proxy."""
    if model is None:
        model = await get_model_for_category(category)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.LITELLM_BASE_URL}/v1/embeddings",
            headers=_auth_headers(),
            json={"model": model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]


async def generate_image(
    prompt: str,
    model: str | None = None,
    category: str = "image",
    size: str = "1024x1024",
    n: int = 1,
) -> str:
    """Generate an image via the LiteLLM proxy and return the first image URL."""
    if model is None:
        model = await get_model_for_category(category)

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
        return data["data"][0]["url"]
