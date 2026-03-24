from __future__ import annotations

import logging
from enum import Enum

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.portal import publish_notification, sse_stream
from app.teams import send_approval_notification, send_failure_alert, send_teams_message

logger = logging.getLogger("notifications")

app = FastAPI(
    title="MARKAI Notifications Service",
    version="0.1.0",
)


# ── Request / Response Models ──────────────────────────────────────


class NotifyChannel(str, Enum):
    teams = "teams"
    portal = "portal"


class NotifyRequest(BaseModel):
    channel: NotifyChannel
    # Common fields
    subject: str | None = None
    body: str = ""
    # Portal (in-app) specific
    user_id: str | None = None
    # Structured notification types
    notification_type: str | None = None  # "approval", "failure_alert", "general"
    # Context for structured types
    content_title: str | None = None
    brand_name: str | None = None
    job_name: str | None = None
    error_message: str | None = None
    entity_info: str | None = None


class NotifyResponse(BaseModel):
    status: str
    channel: str
    detail: str | None = None


# ── Endpoints ──────────────────────────────────────────────────────


@app.post("/notify", response_model=NotifyResponse)
async def notify(req: NotifyRequest):
    try:
        if req.channel == NotifyChannel.teams:
            return await _handle_teams(req)
        elif req.channel == NotifyChannel.portal:
            return await _handle_portal(req)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {req.channel}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Notification send failed: channel=%s", req.channel)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _handle_teams(req: NotifyRequest) -> NotifyResponse:
    if req.notification_type == "failure_alert" and req.job_name:
        await send_failure_alert(
            job_name=req.job_name,
            error=req.error_message or "Unknown error",
            entity_info=req.entity_info or "",
        )
        return NotifyResponse(status="sent", channel="teams", detail="Failure alert sent")

    if req.notification_type == "approval" and req.content_title:
        await send_approval_notification(
            content_title=req.content_title,
            brand_name=req.brand_name or "",
        )
        return NotifyResponse(status="sent", channel="teams", detail="Approval notification sent")

    # General Teams message
    await send_teams_message(
        title=req.subject or "MARKAI Notification",
        text=req.body,
    )
    return NotifyResponse(status="sent", channel="teams", detail="Teams message sent")


async def _handle_portal(req: NotifyRequest) -> NotifyResponse:
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id is required for portal notifications")

    notification_data = {
        "type": req.notification_type or "general",
        "subject": req.subject or "",
        "body": req.body,
        "content_title": req.content_title,
        "brand_name": req.brand_name,
    }

    await publish_notification(user_id=req.user_id, notification=notification_data)
    return NotifyResponse(status="sent", channel="portal", detail="Published to user stream")


@app.get("/stream/{user_id}")
async def stream_notifications(user_id: str):
    """SSE endpoint for real-time in-app notifications for a specific user."""
    return EventSourceResponse(sse_stream(user_id))


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "notifications"}
