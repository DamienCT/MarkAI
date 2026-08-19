"""LiteLLM client wrapper.  All LLM calls route through the LiteLLM proxy.

Never import openai directly — every request goes via LITELLM_BASE_URL.
Models are resolved dynamically from the backend's active model selections
and passed as bare LiteLLM model_names; the proxy's config owns the
provider mapping (OpenAI, Gemini, Anthropic, local GPU), so switching
providers is config-only. Image generation is the exception: it calls the
provider APIs directly (OpenAI images endpoint / Gemini generate_content)
because the pinned proxy doesn't reliably route image payloads.

``generate_image`` additionally runs every rendered frame through
``shared.image_text_guard`` and re-rolls frames that contain hallucinated
lettering — see that module for why the defence lives in the app rather than
in the prompt.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)

from shared.config import settings  # noqa: E402


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


def accumulate_tokens(state: dict, result: "ChatResult") -> None:
    """Add token counts from a ChatResult to the running total in state.

    Accumulates into ``state["_total_tokens"]``, ``state["_total_prompt_tokens"]``,
    and ``state["_total_completion_tokens"]``.
    """
    state["_total_tokens"] = state.get("_total_tokens", 0) + getattr(
        result, "total_tokens", 0
    )
    state["_total_prompt_tokens"] = state.get("_total_prompt_tokens", 0) + getattr(
        result, "prompt_tokens", 0
    )
    state["_total_completion_tokens"] = state.get(
        "_total_completion_tokens", 0
    ) + getattr(result, "completion_tokens", 0)


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

    def __new__(
        cls,
        content: str = "",
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ):
        instance = super().__new__(cls, content)
        instance.prompt_tokens = prompt_tokens
        instance.completion_tokens = completion_tokens
        instance.total_tokens = total_tokens
        return instance


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors worth retrying."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
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
    "text": "gpt-5.6-sol",
    "text-fast": "gpt-5.6-luna",
    "image": "gemini-3.1-flash-image",
    "image-edit": "gemini-3.1-flash-image",
    "video": "veo-3.1-fast-generate-preview",
    "embedding": "text-embedding-3-small",
    "vision": "gpt-5.6-sol",
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

    Returns the model name as registered in the LiteLLM proxy's model_list
    (e.g. "gpt-5.6-sol", "claude-sonnet-5", "gemini-3.7-flash"). The proxy
    config owns the provider mapping, so any provider — including a local
    GPU server — is reachable without code changes here.
    """
    now = time.time()

    # Check cache
    if category in _model_cache:
        model_id, expiry = _model_cache[category]
        if now < expiry:
            return model_id

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
            return active_models[category]
    except Exception:
        # Backend unreachable — use cached value if available (even if expired)
        if category in _model_cache:
            model_id, _ = _model_cache[category]
            return model_id

    # Ultimate fallback
    fallback = _FALLBACK_MODELS.get(category, _FALLBACK_MODELS["text"])
    _model_cache[category] = (fallback, now + _CACHE_TTL)
    return fallback


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from LLM output."""
    return re.sub(r"^```\w*\n?|```$", "", text.strip(), flags=re.MULTILINE).strip()


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
        logger.warning(
            "Failed to parse LLM JSON output (length=%d), falling back to default value: %s...",
            len(text),
            text[:200],
        )
        if fallback is not None:
            logger.warning(
                "parse_llm_json: using fallback value of type %s",
                type(fallback).__name__,
            )
        return fallback


def validate_llm_output(
    data: Any, required_fields: list[str] | None = None, expect_list: bool = False
) -> bool:
    """Validate that LLM output meets basic structural expectations."""
    if expect_list:
        if not isinstance(data, list):
            logger.warning("Expected list from LLM, got %s", type(data).__name__)
            return False
        if required_fields and data:
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    logger.warning(
                        "LLM list item %d is not a dict: %s", idx, type(item).__name__
                    )
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
        raise RuntimeError(
            f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            logger.error(
                "LLM API %d error: %s",
                exc.response.status_code,
                exc.response.text[:500],
            )
        # Let tenacity retry handle transient errors (429, 5xx, timeouts)
        raise
    except httpx.TimeoutException:
        raise TimeoutError(
            f"LLM call timed out after {call_timeout}s (model={model}, max_tokens={max_tokens})"
        )


# Human-readable labels for each report type, used in the plain-English
# summary prompt so the LLM frames its output for the right document.
_REPORT_TYPE_LABELS: dict[str, str] = {
    "research": "market research report",
    "strategy": "marketing strategy",
    "planning": "marketing plan",
    "content_calendar": "content calendar strategy",
}


async def generate_executive_summary_plain(
    report_type: str, payload: dict[str, Any], extra_rules: str = ""
) -> str:
    """Produce a 3-4 sentence plain-English summary of a report.

    Written for non-marketing readers (IT, finance, ops): no jargon, and any
    specialized marketing term that must appear is defined inline in the same
    sentence. Returns "" on failure so callers can degrade gracefully — the
    frontend hides the summary block when this is empty. Callers may pass
    extra_rules to append report-specific hard constraints to the system prompt.
    """
    label = _REPORT_TYPE_LABELS.get(report_type, "report")
    try:
        # Trim the payload so we don't blow the context window on huge reports.
        payload_json = json.dumps(payload, default=str)[:12000]
    except (TypeError, ValueError):
        payload_json = str(payload)[:12000]

    messages = [
        {
            "role": "system",
            "content": (
                "You write plain-English executive summaries for business "
                "documents. Your reader is NOT a marketer — assume they work "
                "in IT, finance, or operations and have never seen marketing "
                "jargon. Rules:\n"
                "- 3 to 4 sentences. No more.\n"
                "- State what this document covers, the single most important "
                "finding, and the main recommended action.\n"
                "- Plain words only. If you must use a specialized term "
                "(e.g. 'content pillar', 'persona', 'positioning'), define it "
                "in the same sentence in parentheses.\n"
                "- No bullet points, no headings, no markdown. Just sentences.\n"
                "- Concrete and specific. Use real numbers from the data.\n"
                + (f"{extra_rules}\n" if extra_rules else "")
                + "Return ONLY the summary text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"This is a {label}. Summarize it for a non-marketing reader.\n\n"
                f"Report data (JSON):\n{payload_json}"
            ),
        },
    ]
    try:
        result = await chat_completion(messages, temperature=0.4, max_tokens=400)
        return str(result or "").strip().strip('"')
    except Exception as exc:  # noqa: BLE001 — summary is best-effort
        logger.warning(
            "generate_executive_summary_plain failed for %s: %s", report_type, exc
        )
        return ""


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
        raise RuntimeError(
            f"Cannot connect to LiteLLM at {settings.LITELLM_BASE_URL} — is the service running?"
        )
    except httpx.TimeoutException:
        raise
    except httpx.HTTPStatusError:
        raise


# Sizes each model family actually accepts. Requested sizes are mapped to the
# nearest one for whichever model is being tried, so a fallback model never
# receives a size that was chosen for a different model (a common 400 cause).
_GPT_IMAGE_SIZES = {"square": "1024x1024", "landscape": "1536x1024", "portrait": "1024x1536"}

# HTTP statuses worth retrying on the SAME model before falling back — these
# are transient (server/load) rather than a permanent rejection of the request.
_TRANSIENT_IMAGE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
_IMAGE_SUBATTEMPTS = 3


def _aspect_of(size: str) -> str:
    """Classify a 'WxH' size string as square / landscape / portrait."""
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except (ValueError, AttributeError):
        return "square"
    if w > h:
        return "landscape"
    if h > w:
        return "portrait"
    return "square"


def _size_for_model(model: str, requested_size: str) -> str:
    """Map a requested size to the nearest size the given model supports."""
    aspect = _aspect_of(requested_size)
    if "gpt-image" in model:
        return _GPT_IMAGE_SIZES[aspect]
    return requested_size


_GEMINI_ASPECT_RATIOS = {"square": "1:1", "landscape": "3:2", "portrait": "2:3"}


def _is_gemini_image_model(model: str) -> bool:
    return model.startswith("gemini") and "image" in model


async def _generate_image_gemini(model: str, prompt: str, size: str) -> str:
    """Generate an image with a Gemini image model; returns a data URI."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not set — required for Gemini image generation")

    from google import genai
    from google.genai import types as gtypes

    aspect = _GEMINI_ASPECT_RATIOS[_aspect_of(size)]
    client = genai.Client(api_key=gemini_key)

    def _call():
        try:
            config = gtypes.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=gtypes.ImageConfig(aspect_ratio=aspect),
            )
        except (AttributeError, TypeError):
            # Older google-genai without ImageConfig — aspect goes in the prompt.
            config = gtypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])
        return client.models.generate_content(
            model=model,
            contents=[f"{prompt}\n\nGenerate the image with a {aspect} aspect ratio."],
            config=config,
        )

    response = await asyncio.to_thread(_call)
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if part.inline_data is not None:
                b64 = base64.b64encode(part.inline_data.data).decode()
                return f"data:image/png;base64,{b64}"
    raise ValueError(f"Gemini image model {model} returned no image data")


async def _get_channel_fallback_model(channel: str, category: str) -> str | None:
    """Look up the configured fallback model for (channel, category) in the
    channel_model_fallbacks table. Returns the model_id if a row exists and
    is_active=true, otherwise None. Best-effort: any DB error returns None
    so the caller falls through to the hardcoded safety net."""
    try:
        from shared.tools.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT model_id FROM channel_model_fallbacks "
                    "WHERE channel = :channel AND category = :category "
                    "AND is_active = true LIMIT 1"
                ),
                {"channel": channel.lower(), "category": category},
            )
            row = result.first()
            return row[0] if row else None
    except Exception as exc:
        logger.debug("Channel fallback lookup failed for %s/%s: %s", channel, category, exc)
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=_retry_on_transient,
    reraise=True,
)
async def _generate_image_once(
    prompt: str,
    model: str | None = None,
    category: str = "image",
    size: str = "1024x1024",
    n: int = 1,
    channel: str | None = None,
) -> str:
    """One render: the provider cascade, with no text guard around it.

    ``generate_image`` is the public entry point — it wraps this in the
    hallucinated-text guard. Call this directly only when a caller genuinely
    must bypass the guard.

    Tries LiteLLM proxy first; falls back to direct OpenAI API if proxy returns 400.
    Handles both url and b64_json response formats.

    The fallback cascade, in order:
      1. primary model (param `model` or the active model for `category`)
      2. per-channel fallback (if `channel` supplied and a row exists in
         channel_model_fallbacks with is_active=true)
      3. hardcoded ultimate safety net `gpt-image-1`
    Duplicates are removed so we never retry the same model twice.
    """
    if model is None:
        model = await get_model_for_category(category)

    # Strip "openai/" prefix — we use the raw model name
    raw_model = model.replace("openai/", "") if model.startswith("openai/") else model

    # Image generation goes directly to OpenAI API (LiteLLM doesn't reliably proxy image endpoints)
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY not set — required for image generation")

    # Build the fallback cascade. The hardcoded gpt-image-1 stays as the
    # ultimate safety net so an empty channel_model_fallbacks table keeps
    # today's behaviour unchanged.
    _IMAGE_FALLBACK = "gpt-image-1"
    models_to_try: list[str] = [raw_model]

    if channel:
        channel_fallback = await _get_channel_fallback_model(channel, category)
        if channel_fallback and channel_fallback not in models_to_try:
            models_to_try.append(channel_fallback)

    if _IMAGE_FALLBACK not in models_to_try:
        models_to_try.append(_IMAGE_FALLBACK)

    last_error: Exception | None = None
    for attempt_model in models_to_try:
        # Send each model a size it actually supports (square stays square so
        # Instagram is never letterboxed into landscape).
        model_size = _size_for_model(attempt_model, size)
        # Retry the SAME model on transient errors (e.g. 520) before falling
        # back — those are flaky, not a permanent rejection.
        for sub_attempt in range(_IMAGE_SUBATTEMPTS):
            try:
                if _is_gemini_image_model(attempt_model):
                    logger.info(
                        "Generating image with model=%s size=%s via Gemini API (try %d/%d)",
                        attempt_model, model_size, sub_attempt + 1, _IMAGE_SUBATTEMPTS,
                    )
                    return await _generate_image_gemini(attempt_model, prompt, model_size)

                logger.info(
                    "Generating image with model=%s size=%s via direct OpenAI API (try %d/%d)",
                    attempt_model, model_size, sub_attempt + 1, _IMAGE_SUBATTEMPTS,
                )
                client = get_http_client()
                # Build request body. gpt-image-* takes quality="high" and
                # background="opaque" for photorealistic output. dall-e-* is
                # retired at OpenAI so we no longer emit those params.
                body: dict = {
                    "model": attempt_model,
                    "prompt": prompt,
                    "size": model_size,
                    "n": n,
                }
                if "gpt-image" in attempt_model:
                    body["quality"] = "high"
                    body["background"] = "opaque"
                resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    json=body,
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
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                # Capture the response body — the real 400 reason lives here,
                # not in the status code alone.
                try:
                    body_text = exc.response.text[:500]
                except Exception:
                    body_text = "<unreadable>"
                if status in _TRANSIENT_IMAGE_STATUS and sub_attempt < _IMAGE_SUBATTEMPTS - 1:
                    logger.warning(
                        "Image model %s transient %d (try %d/%d) — retrying. Body: %s",
                        attempt_model, status, sub_attempt + 1, _IMAGE_SUBATTEMPTS, body_text,
                    )
                    await asyncio.sleep(2 * (sub_attempt + 1))
                    continue
                logger.warning(
                    "Image model %s returned %d — trying next model. Body: %s",
                    attempt_model, status, body_text,
                )
                break  # permanent error or retries exhausted — next model
            except Exception as exc:
                last_error = exc
                if sub_attempt < _IMAGE_SUBATTEMPTS - 1:
                    logger.warning(
                        "Image model %s error (try %d/%d) — retrying: %s",
                        attempt_model, sub_attempt + 1, _IMAGE_SUBATTEMPTS, exc,
                    )
                    await asyncio.sleep(2 * (sub_attempt + 1))
                    continue
                logger.warning(
                    "Image model %s failed: %s — trying next model", attempt_model, exc
                )
                break

    raise RuntimeError(f"All image models failed. Last error: {last_error}")


async def generate_image(
    prompt: str,
    model: str | None = None,
    category: str = "image",
    size: str = "1024x1024",
    n: int = 1,
    channel: str | None = None,
    *,
    allowed_text: Sequence[str] | str | None = None,
    text_guard: bool | None = None,
    guard_label: str | None = None,
) -> str:
    """Generate an image, re-rolling frames that contain hallucinated text.

    Every image path in the app funnels through here, so this is the single
    place the app defends itself against the one defect that makes a generated
    frame unpublishable: lettering the brief never asked for. Image models
    invent labels on blank containers and garble signage, and neither a
    negative prompt nor a higher CFG reliably suppresses it — so a rendered
    frame is vision-checked (``shared.image_text_guard``) and, if it trips,
    re-rendered with a strengthened no-text instruction and a fresh variation
    seed.

    ``allowed_text`` declares what lettering is legitimate for THIS image — a
    real product's own packaging, a storefront the brief specified. The default
    ``None`` means none is, which matches every prompt template in this repo
    (they all say "NO text, NO words, NO letters"). Garbled or misspelled
    lettering is rejected either way, even on a legitimate label.

    Cost is bounded twice over: by ``IMAGE_TEXT_GUARD_MAX_RETRIES`` and by the
    hard ``image_text_guard.MAX_RETRY_CAP``. Once the budget is spent the least
    bad attempt is returned rather than raising — a post with a flawed image
    still beats no post, and the rejection is in the logs either way.

    Pass ``text_guard=False`` (or set ``IMAGE_TEXT_GUARD_ENABLED=false``) to
    skip the check entirely and get a single plain render.
    """
    from shared import image_text_guard as guard  # lazy — avoids an import cycle

    enabled = guard.guard_enabled() if text_guard is None else bool(text_guard)
    if not enabled:
        return await _generate_image_once(prompt, model, category, size, n, channel)

    label = guard_label or category
    retries = guard.retry_cap()
    max_attempts = retries + 1

    best_ref: str | None = None
    best_severity: int | None = None
    attempt_prompt = prompt
    seed: int | None = None

    for attempt in range(max_attempts):
        image_ref = await _generate_image_once(
            attempt_prompt, model, category, size, n, channel
        )
        verdict = await guard.inspect_image(
            image_ref, allowed_text=allowed_text, label=label
        )

        if not verdict.flagged:
            if attempt:
                logger.info(
                    "image_text_guard.recovered label=%s attempt=%d/%d",
                    label,
                    attempt + 1,
                    max_attempts,
                )
            return image_ref

        guard.log_rejection(
            label=label,
            attempt=attempt + 1,
            max_attempts=max_attempts,
            verdict=verdict,
            model=model or category,
            seed=seed,
        )

        if best_severity is None or verdict.severity < best_severity:
            best_ref, best_severity = image_ref, verdict.severity

        if attempt < max_attempts - 1:
            attempt_prompt, seed = guard.strengthen_prompt(prompt, verdict, attempt + 1)

    logger.warning(
        "image_text_guard.exhausted label=%s attempts=%d — publishing best "
        "attempt (severity=%s)",
        label,
        max_attempts,
        best_severity,
    )
    return best_ref  # type: ignore[return-value]
