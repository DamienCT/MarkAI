"""LiteLLM client wrapper.  All LLM calls route through the LiteLLM proxy.

Never import openai directly — every request goes via LITELLM_BASE_URL.
Models are resolved dynamically from the backend's active model selections.
The real OpenAI model ID is passed with "openai/" prefix so LiteLLM routes
it correctly without needing hardcoded model_list entries.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)

from shared.config import settings


# ── Shared httpx client (lazy singleton) ────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return a module-level shared httpx.AsyncClient, creating it lazily."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_connections=20),
        )
    return _http_client


class ChatResult(str):
    """Return type for chat_completion — behaves like a str (the content)
    but also carries token usage metadata.

    Callers that just do ``str(result)`` or use it as a string continue to work.
    Callers that need usage can access ``.prompt_tokens``, ``.completion_tokens``,
    and ``.total_tokens``.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __new__(cls, content: str = "", *, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0):
        instance = super().__new__(cls, content)
        instance.prompt_tokens = prompt_tokens
        instance.completion_tokens = completion_tokens
        instance.total_tokens = total_tokens
        return instance


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

        client = get_http_client()
        resp = await client.get(
            f"{backend_url}/api/v1/providers/active",
            headers=_auth_headers(),
            timeout=10,
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
        result = json.loads(cleaned)
        # response_format={"type":"json_object"} wraps arrays in a single-key dict
        # e.g. {"competitors": [...]} — unwrap to just the list
        if isinstance(result, dict) and len(result) == 1:
            only_value = next(iter(result.values()))
            if isinstance(only_value, list):
                return only_value
        return result
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
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    logger.warning("LLM list item %d is not a dict: %s", idx, type(item).__name__)
                    return False
                missing = [f for f in required_fields if f not in item]
                if missing:
                    logger.warning("LLM list item %d missing fields: %s", idx, missing)
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
    response_format: dict[str, str] | None = None,
) -> "ChatResult":
    """Send a chat completion request through the LiteLLM proxy and return
    the assistant message content.

    If ``model`` is not provided, the active model for the given ``category``
    is resolved dynamically from the backend.
    """
    if model is None:
        model = await get_model_for_category(category)

    try:
        client = get_http_client()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            body["response_format"] = response_format
        # Scale timeout with max_tokens — large generations (16K tokens) need more time
        call_timeout = max(120, min(600, max_tokens // 10))
        resp = await client.post(
            f"{settings.LITELLM_BASE_URL}/v1/chat/completions",
            headers=_auth_headers(),
            json=body,
            timeout=call_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return ChatResult(
            content=content,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
    except httpx.ConnectError:
        raise RuntimeError(f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            logger.error("LLM API %d error: %s", exc.response.status_code, exc.response.text[:500])
        # Let tenacity retry handle transient errors (429, 5xx, timeouts)
        raise
    except httpx.TimeoutException:
        raise TimeoutError(f"LLM call timed out after {call_timeout}s (model={model}, max_tokens={max_tokens})")


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
        client = get_http_client()
        resp = await client.post(
            f"{settings.LITELLM_BASE_URL}/v1/embeddings",
            headers=_auth_headers(),
            json={"model": model, "input": text},
            timeout=60,
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
    """Generate an image and return the first image URL or data URI.

    Tries LiteLLM proxy first; falls back to direct OpenAI API if proxy returns 400.
    Handles both url and b64_json response formats.
    """
    if model is None:
        model = await get_model_for_category(category)

    # Strip "openai/" prefix — we use the raw model name
    raw_model = model.replace("openai/", "") if model.startswith("openai/") else model

    # Image generation goes directly to OpenAI API (LiteLLM doesn't reliably proxy image endpoints)
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY not set — required for image generation")

    logger.info("Generating image with model=%s via direct OpenAI API", raw_model)
    client = get_http_client()
    resp = await client.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {openai_key}"},
        json={
            "model": raw_model,
            "prompt": prompt,
            "size": size,
            "n": n,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data["data"][0]

    if result.get("url"):
        return result["url"]
    elif result.get("b64_json"):
        return f"data:image/png;base64,{result['b64_json']}"
    else:
        raise ValueError("Image generation returned neither url nor b64_json")
