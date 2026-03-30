import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.models.calendar_item import CalendarItem
from app.services import content_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_webhook_secret(request: Request) -> None:
    """Validate X-Webhook-Secret header against configured secret."""
    configured_secret = settings.N8N_WEBHOOK_SECRET
    if not configured_secret:
        logger.error("N8N_WEBHOOK_SECRET is not configured; rejecting webhook call")
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    incoming_secret = request.headers.get("X-Webhook-Secret", "")
    if not secrets.compare_digest(incoming_secret, configured_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


class PublishResultPayload(BaseModel):
    """Payload received from n8n after a publish attempt."""

    content_id: str
    status: str  # "published" or "failed"
    platform_post_id: str | None = None
    error_message: str | None = None
    published_at: str | None = None


@router.post("/publish-result")
async def publish_result(
    request: Request,
    payload: PublishResultPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Callback from n8n after attempting to publish content.
    Updates the calendar item status and content's platform_post_id.
    """
    _verify_webhook_secret(request)
    import uuid

    content_id = uuid.UUID(payload.content_id)
    content = await content_service.get_content(db, content_id)

    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    if payload.status == "published":
        if not payload.platform_post_id:
            logger.warning("Published callback for content %s missing platform_post_id", content_id)
        content.platform_post_id = payload.platform_post_id

        # Update the associated calendar item's status and published_at
        if content.calendar_item_id:
            result = await db.execute(
                select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
            )
            cal_item = result.scalar_one_or_none()
            if cal_item is not None:
                cal_item.status = "published"
                cal_item.published_at = (
                    datetime.fromisoformat(payload.published_at)
                    if payload.published_at
                    else datetime.now(timezone.utc)
                )

        logger.info(
            "Content %s published, platform_post_id=%s",
            content_id,
            payload.platform_post_id,
        )
    elif payload.status == "failed":
        # Update calendar item status to failed
        if content.calendar_item_id:
            result = await db.execute(
                select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
            )
            cal_item = result.scalar_one_or_none()
            if cal_item is not None:
                cal_item.status = "failed"

        # Store error in generation_metadata
        gen_meta = content.generation_metadata or {}
        gen_meta["publish_error"] = payload.error_message
        content.generation_metadata = gen_meta

        logger.warning(
            "Content %s publish failed: %s", content_id, payload.error_message
        )
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be 'published' or 'failed'.",
        )

    await db.commit()
    await db.refresh(content)

    return {"content_id": str(content.id), "status": payload.status}
