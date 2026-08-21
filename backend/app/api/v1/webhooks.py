import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.deps import get_db
from app.models.calendar_item import CalendarItem
from app.services import content_service

logger = logging.getLogger(__name__)

router = APIRouter()

# A callback may only move a calendar item FORWARD through the publish
# lifecycle. Everything else — a replayed/late 'failed' for an item already
# 'published' (which would invite a duplicate retry), or any callback for an
# item an operator pulled back out of the queue — is ignored with a 200.
_ALLOWED_CALLBACK_TRANSITIONS = {
    ("publishing", "published"),
    ("publishing", "failed"),
    ("scheduled", "published"),
    ("scheduled", "failed"),
}


def _hmac_secret() -> str:
    # Seam (also for tests): blank = legacy static-secret mode.
    return settings.N8N_WEBHOOK_HMAC_SECRET or ""


def _parse_timestamp(raw: str) -> float:
    """Accept unix seconds (preferred) or an ISO-8601 datetime (legacy)."""
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        ts = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail="Invalid X-Webhook-Timestamp format"
        )
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


def _check_timestamp_window(ts_header: str) -> None:
    ts = _parse_timestamp(ts_header)
    if abs(time.time() - ts) > 300:  # 5 minutes
        raise HTTPException(
            status_code=403, detail="Webhook timestamp too old or in the future"
        )


async def _verify_webhook_auth(request: Request) -> None:
    """Static shared secret always; body-bound HMAC when the HMAC secret is set."""
    configured_secret = settings.N8N_WEBHOOK_SECRET
    if not configured_secret:
        logger.error("N8N_WEBHOOK_SECRET is not configured; rejecting webhook call")
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    incoming_secret = request.headers.get("X-Webhook-Secret", "")
    if not secrets.compare_digest(incoming_secret, configured_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    hmac_secret = _hmac_secret()
    ts_header = request.headers.get("X-Webhook-Timestamp", "")

    if hmac_secret:
        # HMAC mode: timestamp + signature are REQUIRED and body-bound —
        # sha256=hex(hmac_sha256(secret, timestamp + "." + raw_body)).
        if not ts_header:
            raise HTTPException(
                status_code=403, detail="Missing X-Webhook-Timestamp"
            )
        _check_timestamp_window(ts_header)
        sig_header = request.headers.get("X-Webhook-Signature", "")
        if not sig_header.startswith("sha256="):
            raise HTTPException(
                status_code=403, detail="Missing or malformed X-Webhook-Signature"
            )
        raw_body = await request.body()
        expected = hmac.new(
            hmac_secret.encode(),
            ts_header.encode() + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not secrets.compare_digest(sig_header[len("sha256="):], expected):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        return

    # Legacy mode (HMAC secret not yet provisioned / n8n workflow not yet
    # re-imported): static secret only — replayable, deployment-staging only.
    logger.warning(
        "Webhook accepted with static secret only — set N8N_WEBHOOK_HMAC_SECRET "
        "and re-import the n8n workflow to enable signed callbacks "
        "(deprecated path)"
    )
    if ts_header:
        _check_timestamp_window(ts_header)


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
    Updates the calendar item status and content's platform_post_id —
    but only through legal monotonic transitions, exactly once per event id.
    """
    await _verify_webhook_auth(request)

    # Event-id replay guard: the first delivery consumes the id, replays
    # no-op with a 200 (n8n retries / captured-callback replays).
    event_id = request.headers.get("X-Webhook-Event-Id", "")
    if event_id:
        inserted = await db.execute(
            text(
                "INSERT INTO webhook_events (event_id) VALUES (:event_id) "
                "ON CONFLICT (event_id) DO NOTHING"
            ),
            {"event_id": event_id},
        )
        if (inserted.rowcount or 0) == 0:
            logger.info(
                "Replayed webhook event %s for content %s ignored",
                event_id,
                payload.content_id,
            )
            return {"content_id": payload.content_id, "status": "duplicate"}

    if payload.status not in ("published", "failed"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be 'published' or 'failed'.",
        )

    try:
        content_id = uuid.UUID(payload.content_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid content_id")
    content = await content_service.get_content(db, content_id)

    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    cal_item = None
    if content.calendar_item_id:
        result = await db.execute(
            select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
        )
        cal_item = result.scalar_one_or_none()

    # Monotonic transition guard — ALWAYS enforced. A late/replayed 'failed'
    # can never regress a 'published' item, and no callback overwrites an
    # operator's cancellation (any status outside scheduled/publishing).
    if (
        cal_item is not None
        and (cal_item.status, payload.status) not in _ALLOWED_CALLBACK_TRANSITIONS
    ):
        logger.warning(
            "Ignoring publish callback for content %s: transition %s→%s "
            "is not allowed",
            content_id,
            cal_item.status,
            payload.status,
        )
        await db.commit()  # keep the consumed event id
        return {
            "content_id": str(content_id),
            "status": "ignored",
            "detail": (
                f"transition {cal_item.status}→{payload.status} not allowed"
            ),
        }

    if payload.status == "published":
        if not payload.platform_post_id:
            logger.warning(
                "Published callback for content %s missing platform_post_id", content_id
            )
        content.platform_post_id = payload.platform_post_id

        if cal_item is not None:
            cal_item.status = "published"
            # Don't trust the callback's timestamp verbatim: a malformed
            # value must not 500 (post-auth) or poison the row — clamp to
            # the current time and log it.
            published_at = datetime.now(timezone.utc)
            if payload.published_at:
                try:
                    published_at = datetime.fromisoformat(payload.published_at)
                except (ValueError, TypeError):
                    logger.warning(
                        "Malformed published_at %r in publish callback for "
                        "content %s — using current UTC time",
                        payload.published_at,
                        content_id,
                    )
            cal_item.published_at = published_at

        logger.info(
            "Content %s published, platform_post_id=%s",
            content_id,
            payload.platform_post_id,
        )
    else:
        if cal_item is not None:
            cal_item.status = "failed"

        # Store error in generation_metadata
        gen_meta = content.generation_metadata or {}
        gen_meta["publish_error"] = payload.error_message
        content.generation_metadata = gen_meta
        flag_modified(content, "generation_metadata")

        logger.warning(
            "Content %s publish failed: %s", content_id, payload.error_message
        )

    await db.commit()
    await db.refresh(content)

    return {"content_id": str(content.id), "status": payload.status}
