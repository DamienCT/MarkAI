"""Scheduled job for AI model discovery."""

import logging

logger = logging.getLogger(__name__)


async def discover_ai_models():
    """Daily job: query OpenAI API for available models, update DB."""
    from app.services.ai_model_service import discover_models

    try:
        result = await discover_models()
        logger.info(
            "AI model discovery completed: %d discovered, %d updated, %d unavailable",
            result["discovered"],
            result["updated"],
            result["unavailable"],
        )
    except Exception as exc:
        logger.error("AI model discovery failed: %s", exc, exc_info=True)
        raise
