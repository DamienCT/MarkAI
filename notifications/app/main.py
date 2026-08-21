from __future__ import annotations

import logging
from enum import Enum

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.auth import (
    DEFAULT_STREAM_TOKEN_TTL_S,
    mint_stream_token,
    service_token_valid,
    verify_stream_token,
)
from app.config import settings
from app.portal import publish_notification, sse_stream
from app.teams import send_approval_notification, send_failure_alert, send_teams_message

logger = logging.getLogger("notifications")

def _anon_allowed() -> bool:
    """The dev escape hatch never applies in production (fail closed)."""
    return settings.NOTIFICATIONS_ALLOW_ANON and settings.MARKAI_ENV != "production"


if not settings.NOTIFICATIONS_AUTH_TOKEN:
    if _anon_allowed():
        logger.critical(
            "NOTIFICATIONS_AUTH_TOKEN is blank and NOTIFICATIONS_ALLOW_ANON=true — "
            "running UNAUTHENTICATED. Local development only; never in production."
        )
    else:
        logger.critical(
            "NOTIFICATIONS_AUTH_TOKEN is not set — all /notify and /stream "
            "requests will be refused (503) until a token is configured "
            "(the ALLOW_ANON escape hatch is inert in production)."
        )


async def verify_service_token(
    x_auth_token: str = Header("", alias="X-Auth-Token"),
) -> None:
    """Shared-token auth for service-to-service calls (fail closed on blank)."""
    if not settings.NOTIFICATIONS_AUTH_TOKEN:
        if _anon_allowed():
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "NOTIFICATIONS_AUTH_TOKEN is not configured; refusing all requests. "
                "Set the token, or NOTIFICATIONS_ALLOW_ANON=true for local dev only."
            ),
        )
    if not service_token_valid(settings.NOTIFICATIONS_AUTH_TOKEN, x_auth_token):
        raise HTTPException(status_code=401, detail="Invalid auth token")


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


class StreamTokenRequest(BaseModel):
    user_id: str = Field(min_length=1)
    ttl_seconds: int = DEFAULT_STREAM_TOKEN_TTL_S


class StreamTokenResponse(BaseModel):
    user_id: str
    token: str
    expires_at: int


# ── Endpoints ──────────────────────────────────────────────────────


@app.post("/notify", response_model=NotifyResponse, dependencies=[Depends(verify_service_token)])
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


@app.post(
    "/stream/token",
    response_model=StreamTokenResponse,
    dependencies=[Depends(verify_service_token)],
)
async def create_stream_token(req: StreamTokenRequest):
    """Mint a per-user, expiring SSE token (service auth required).

    The backend calls this on behalf of a signed-in user, then hands the
    token to the browser — the shared service token never leaves the server
    side, and the minted token only opens that user's stream.
    """
    if not settings.NOTIFICATIONS_AUTH_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="NOTIFICATIONS_AUTH_TOKEN is not configured; cannot mint stream tokens",
        )
    token, expires_at = mint_stream_token(
        settings.NOTIFICATIONS_AUTH_TOKEN, req.user_id, req.ttl_seconds
    )
    return StreamTokenResponse(user_id=req.user_id, token=token, expires_at=expires_at)


@app.get("/stream/{user_id}")
async def stream_notifications(user_id: str, token: str = Query("")):
    """SSE endpoint for real-time in-app notifications for a specific user.

    Requires a per-user HMAC token from POST /stream/token — the token is
    bound to *user_id* and expires, so one user's token can never open
    another user's stream (and the global service token is never accepted
    here, keeping it out of query strings and access logs).
    """
    if not settings.NOTIFICATIONS_AUTH_TOKEN:
        if _anon_allowed():
            return EventSourceResponse(sse_stream(user_id))
        raise HTTPException(
            status_code=503,
            detail=(
                "NOTIFICATIONS_AUTH_TOKEN is not configured; refusing all requests. "
                "Set the token, or NOTIFICATIONS_ALLOW_ANON=true for local dev only."
            ),
        )
    if not verify_stream_token(settings.NOTIFICATIONS_AUTH_TOKEN, user_id, token):
        raise HTTPException(status_code=401, detail="Invalid or expired stream token")
    return EventSourceResponse(sse_stream(user_id))


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "notifications"}
