"""AI Model management service.

Handles model discovery from OpenAI API, category assignment,
active model selection, and Valkey caching.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ai_model import AIModel, AIModelCategory, AIModelSelection
from app.models.base import async_session_factory

logger = logging.getLogger(__name__)

# Cache TTL in seconds (5 minutes)
_CACHE_TTL = 300

# In-memory fallback cache (used when Valkey is unavailable)
_memory_cache: dict[str, tuple[str, float]] = {}


def _categorize_model(model_id: str) -> list[str]:
    """Determine which category slugs a model ID belongs to.

    A model can belong to multiple categories.
    """
    categories: list[str] = []
    mid = model_id.lower()

    # Image generation
    if re.match(r"^(dall-e-|gpt-image-|chatgpt-image-)", mid):
        categories.append("image")

    # Embeddings
    if re.match(r"^text-embedding-", mid):
        categories.append("embedding")

    # TTS — dedicated TTS models and mini-tts variants
    if re.match(r"^tts[-_]", mid) or "tts" in mid.split("-"):
        categories.append("tts")

    # STT — whisper and transcribe variants
    if re.match(r"^whisper-", mid) or "transcribe" in mid:
        categories.append("stt")

    # Video
    if re.match(r"^(sora-|video-)", mid):
        categories.append("video")

    # Moderation
    if re.match(r"^(omni-moderation-|text-moderation-)", mid):
        categories.append("moderation")

    # Audio / Realtime (categorize as text since they do chat too)
    if "audio" in mid or "realtime" in mid:
        if not categories:
            categories.append("text")

    # Vision — specific vision models and multimodal models (gpt-4o+ have vision)
    if re.match(r"^gpt-4-vision-", mid):
        categories.append("vision")

    # Text-fast — smaller/cheaper models (mini, nano, gpt-3.5)
    if re.match(r"^(gpt-4o-mini|gpt-4\.1-mini|gpt-4\.1-nano|gpt-3\.5|o4-mini)", mid):
        categories.append("text-fast")
    elif re.match(r"^gpt-5(\.\d+)?-(mini|nano)", mid):
        categories.append("text-fast")
    # Text / Chat — general language models (gpt-4+, gpt-5+, o-series)
    elif re.match(r"^(gpt-[45]|chatgpt-|o[134]-|o[134]$)", mid):
        # Exclude models already categorized as image/embedding/tts/stt/video
        skip = {"image", "embedding", "tts", "stt", "video"}
        if not categories or not (set(categories) & skip):
            categories.append("text")

    # Computer use — categorize as text (agent tool use)
    if mid.startswith("computer-use"):
        categories.append("text")

    # Search — categorize as text
    if "search" in mid and not categories:
        categories.append("text")

    # Deep research — text
    if "deep-research" in mid and "text" not in categories:
        categories.append("text")

    return categories


# Module-level Valkey connection pool (reused across all calls)
_valkey_pool = None


def _get_valkey_pool():
    """Get or create the module-level Valkey connection pool."""
    global _valkey_pool
    if _valkey_pool is None:
        try:
            import redis.asyncio as aioredis

            _valkey_pool = aioredis.ConnectionPool(
                host=settings.VALKEY_HOST,
                port=settings.VALKEY_PORT,
                decode_responses=True,
                max_connections=10,
            )
        except Exception:
            pass
    return _valkey_pool


async def _get_valkey_client():
    """Try to get a Valkey (Redis) connection from the pool. Returns None if unavailable."""
    try:
        import redis.asyncio as aioredis

        pool = _get_valkey_pool()
        if pool is None:
            return None
        client = aioredis.Redis(connection_pool=pool)
        await client.ping()
        return client
    except Exception:
        return None


async def _cache_get(key: str) -> str | None:
    """Get a value from cache (Valkey with in-memory fallback)."""
    client = await _get_valkey_client()
    if client:
        try:
            val = await client.get(key)
            return val
        except Exception:
            pass

    # Fallback to memory cache
    import time

    entry = _memory_cache.get(key)
    if entry:
        value, expires = entry
        if time.time() < expires:
            return value
        del _memory_cache[key]
    return None


async def _cache_set(key: str, value: str, ttl: int = _CACHE_TTL) -> None:
    """Set a value in cache (Valkey with in-memory fallback)."""
    client = await _get_valkey_client()
    if client:
        try:
            await client.set(key, value, ex=ttl)
            return
        except Exception:
            pass

    # Fallback to memory cache
    import time

    _memory_cache[key] = (value, time.time() + ttl)


async def _cache_delete_pattern(pattern: str) -> None:
    """Delete all cache keys matching a pattern."""
    client = await _get_valkey_client()
    if client:
        try:
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await client.delete(*keys)
        except Exception:
            pass

    # Clear memory cache for matching keys
    import fnmatch

    to_delete = [k for k in _memory_cache if fnmatch.fnmatch(k, pattern)]
    for k in to_delete:
        del _memory_cache[k]


async def discover_models() -> dict[str, int]:
    """Query OpenAI API for available models and update the database.

    Returns a dict with counts: discovered, updated, unavailable.
    """
    logger.info("Starting AI model discovery from OpenAI API")

    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not configured, skipping model discovery")
        return {"discovered": 0, "updated": 0, "unavailable": 0}

    # Fetch models from OpenAI
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            )
            resp.raise_for_status()
            api_data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch models from OpenAI API: %s", exc)
        raise

    api_models = api_data.get("data", [])
    api_model_ids = {m["id"] for m in api_models}

    logger.info("OpenAI API returned %d models", len(api_models))

    discovered = 0
    updated = 0
    unavailable = 0

    async with async_session_factory() as db:
        # Load existing categories
        cat_result = await db.execute(select(AIModelCategory))
        categories = {c.slug: c for c in cat_result.scalars().all()}

        # Load existing models
        existing_result = await db.execute(
            select(AIModel).where(AIModel.provider == "openai")
        )
        existing_models = {m.model_id: m for m in existing_result.scalars().all()}

        # Process each model from the API
        for api_model in api_models:
            model_id = api_model["id"]
            owned_by = api_model.get("owned_by", "")
            created_ts = api_model.get("created")

            category_slugs = _categorize_model(model_id)

            # Build capabilities metadata
            capabilities = {
                "owned_by": owned_by,
            }
            if created_ts:
                capabilities["created"] = created_ts

            if model_id in existing_models:
                # Update existing model
                existing = existing_models[model_id]
                changed = False
                if not existing.is_available:
                    existing.is_available = True
                    changed = True
                if existing.capabilities != capabilities:
                    existing.capabilities = capabilities
                    changed = True
                # Update category if we have one and it's not set
                if category_slugs and existing.category_id is None:
                    primary_cat = category_slugs[0]
                    if primary_cat in categories:
                        existing.category_id = categories[primary_cat].id
                        changed = True
                if changed:
                    updated += 1
            else:
                # Create new model
                primary_category_id = None
                if category_slugs:
                    primary_cat = category_slugs[0]
                    if primary_cat in categories:
                        primary_category_id = categories[primary_cat].id

                # Generate a human-friendly display name
                display_name = model_id

                new_model = AIModel(
                    provider="openai",
                    model_id=model_id,
                    display_name=display_name,
                    category_id=primary_category_id,
                    is_available=True,
                    capabilities=capabilities,
                )
                db.add(new_model)
                discovered += 1

            # For models with multiple categories, create entries for additional
            # categories (we store the primary via category_id, additional
            # categories are tracked in capabilities)
            if len(category_slugs) > 1:
                if model_id in existing_models:
                    existing_models[model_id].capabilities["additional_categories"] = (
                        category_slugs[1:]
                    )
                # For new models, capabilities already set above

        # Mark models that disappeared from the API as unavailable
        for model_id, existing in existing_models.items():
            if model_id not in api_model_ids and existing.is_available:
                existing.is_available = False
                unavailable += 1

        await db.commit()

    # Invalidate active model cache
    await _cache_delete_pattern("markai:active_model:*")

    logger.info(
        "Model discovery complete: %d discovered, %d updated, %d marked unavailable",
        discovered,
        updated,
        unavailable,
    )
    return {"discovered": discovered, "updated": updated, "unavailable": unavailable}


async def get_active_model(category_slug: str) -> str:
    """Return the active model_id string for a category.

    Uses Valkey cache with 5-minute TTL. Falls back to sensible defaults
    if no model has been selected.
    """
    cache_key = f"markai:active_model:{category_slug}"

    # Check cache
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    # Query database
    async with async_session_factory() as db:
        result = await db.execute(
            select(AIModelSelection, AIModel)
            .join(AIModel, AIModelSelection.model_id == AIModel.id)
            .where(
                AIModelSelection.category_slug == category_slug,
                AIModelSelection.is_active == True,
                AIModel.is_available == True,
            )
            .order_by(AIModelSelection.priority.desc())
            .limit(1)
        )
        row = result.first()

        if row:
            selection, model = row
            model_id_str = model.model_id
            await _cache_set(cache_key, model_id_str)
            return model_id_str

    # Fallback defaults (only used when no selection exists)
    defaults = {
        "text": "gpt-4o",
        "text-fast": "gpt-4o-mini",
        "image": "dall-e-3",
        "embedding": "text-embedding-3-small",
        "tts": "tts-1",
        "stt": "whisper-1",
        "moderation": "omni-moderation-latest",
        "vision": "gpt-4o",
    }
    fallback = defaults.get(category_slug, "gpt-4o")
    await _cache_set(cache_key, fallback)
    return fallback


async def set_active_model(
    category_slug: str,
    model_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> AIModelSelection:
    """Set the active model for a category. Deactivates any previous selection."""
    own_session = db is None
    if own_session:
        db = async_session_factory()

    try:
        if own_session:
            await db.__aenter__()

        # Verify the model exists and is available
        model_result = await db.execute(
            select(AIModel).where(AIModel.id == model_id, AIModel.is_available == True)
        )
        model = model_result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Model {model_id} not found or unavailable")

        # Verify the category exists
        cat_result = await db.execute(
            select(AIModelCategory).where(AIModelCategory.slug == category_slug)
        )
        category = cat_result.scalar_one_or_none()
        if not category:
            raise ValueError(f"Category '{category_slug}' not found")

        # Deactivate existing selections for this category
        await db.execute(
            update(AIModelSelection)
            .where(
                AIModelSelection.category_slug == category_slug,
                AIModelSelection.is_active == True,
            )
            .values(is_active=False)
        )

        # Check if there's an existing selection for this category+model
        existing_result = await db.execute(
            select(AIModelSelection).where(
                AIModelSelection.category_slug == category_slug,
                AIModelSelection.model_id == model_id,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.is_active = True
            existing.set_by = user_id
            existing.set_at = datetime.now(timezone.utc)
            selection = existing
        else:
            selection = AIModelSelection(
                category_slug=category_slug,
                model_id=model_id,
                is_active=True,
                priority=0,
                set_by=user_id,
            )
            db.add(selection)

        await db.commit()
        await db.refresh(selection)

        # Invalidate cache
        cache_key = f"markai:active_model:{category_slug}"
        await _cache_set(cache_key, model.model_id)
        # Also invalidate the full active models cache
        await _cache_delete_pattern("markai:active_models_all")

        return selection
    finally:
        if own_session:
            await db.__aexit__(None, None, None)


async def list_categories(db: AsyncSession) -> list[dict]:
    """Return all categories with their currently active model."""
    result = await db.execute(
        select(AIModelCategory).order_by(AIModelCategory.slug)
    )
    categories = result.scalars().all()

    output = []
    for cat in categories:
        # Get active selection for this category
        sel_result = await db.execute(
            select(AIModelSelection, AIModel)
            .join(AIModel, AIModelSelection.model_id == AIModel.id)
            .where(
                AIModelSelection.category_slug == cat.slug,
                AIModelSelection.is_active == True,
            )
            .order_by(AIModelSelection.priority.desc())
            .limit(1)
        )
        sel_row = sel_result.first()

        active_model = None
        if sel_row:
            _, model = sel_row
            active_model = model

        output.append({
            "id": cat.id,
            "slug": cat.slug,
            "display_name": cat.display_name,
            "description": cat.description,
            "created_at": cat.created_at,
            "active_model": active_model,
        })

    return output


async def list_models_by_category(
    db: AsyncSession, category_slug: str | None = None
) -> list[AIModel]:
    """Return all available models, optionally filtered by category."""
    stmt = select(AIModel).where(AIModel.is_available == True)

    if category_slug:
        # Join with category to filter by slug
        stmt = (
            stmt.join(AIModelCategory, AIModel.category_id == AIModelCategory.id)
            .where(AIModelCategory.slug == category_slug)
        )

    stmt = stmt.order_by(AIModel.model_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_all_active_models(db: AsyncSession) -> dict[str, str]:
    """Return a dict mapping each category slug to its active model_id string."""
    cache_key = "markai:active_models_all"
    cached = await _cache_get(cache_key)
    if cached:
        return json.loads(cached)

    result = await db.execute(
        select(AIModelSelection, AIModel)
        .join(AIModel, AIModelSelection.model_id == AIModel.id)
        .where(AIModelSelection.is_active == True, AIModel.is_available == True)
        .order_by(AIModelSelection.priority.desc())
    )

    models: dict[str, str] = {}
    for selection, model in result.all():
        # Only keep the highest-priority selection per category
        if selection.category_slug not in models:
            models[selection.category_slug] = model.model_id

    await _cache_set(cache_key, json.dumps(models))
    return models
