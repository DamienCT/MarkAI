"""Scheduled check: alert brand owners before their LinkedIn token expires.

Runs every 6h. For each active brand with LinkedIn enabled, resolve the token's
expiry/status (live introspection, or the stored expiry as fallback); if it
expires within the next 10 days (or has already expired), create an in-app
(bell) notification for admins/managers. Repeats on every run — i.e. every 6h —
until the token is renewed (expiry pushed beyond the 10-day window).
"""

import json as _json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.models.base import async_session_factory
from app.services.notification_service import notify_admins

logger = logging.getLogger(__name__)

_ALERT_WINDOW_DAYS = 10


def _parse_expiry(value) -> datetime | None:
    """Parse a stored expiry — accepts epoch seconds (int/str) or ISO 8601."""
    if value is None or value == "":
        return None
    # Epoch seconds (LinkedIn returns these, e.g. 1785755949)
    try:
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and value.strip().lstrip("-").isdigit()
        ):
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    # ISO 8601 (accept a trailing Z)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _introspect_linkedin_token(
    token: str, client_id: str, client_secret: str
) -> dict | None:
    """Call LinkedIn's token introspection API → real expires_at / status.

    Returns the JSON dict (active, status, expires_at, created_at, auth_type,
    scope, ...) or None if creds are missing or the call fails.
    """
    if not (client_id and client_secret and token):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://www.linkedin.com/oauth/v2/introspectToken",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "token": token,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("LinkedIn token introspection failed: %s", exc)
        return None


async def _resolve_token_state(li: dict) -> tuple[datetime | None, str | None]:
    """Resolve (expiry, status) for a brand's LinkedIn config.

    Prefers LIVE introspection (dynamic — no manual date), using the app
    credentials entered in the brand's Channels UI (client_id/client_secret),
    falling back to env settings. Falls back to the manually-entered
    `token_expires_at` field when no app creds are available.
    status is "active"/"expired"/"revoked" from LinkedIn, or None for fallback.
    """
    token = li.get("access_token") or settings.LINKEDIN_ACCESS_TOKEN
    client_id = li.get("client_id") or settings.LINKEDIN_CLIENT_ID
    client_secret = li.get("client_secret") or settings.LINKEDIN_CLIENT_SECRET
    data = await _introspect_linkedin_token(token, client_id, client_secret)
    if data is not None:
        status = data.get("status") or ("active" if data.get("active") else "expired")
        return _parse_expiry(data.get("expires_at")), status
    # Fallback: manual field
    return _parse_expiry(li.get("token_expires_at")), None


async def linkedin_token_expiry_check() -> None:
    """Notify owners whose LinkedIn token is within 10 days of expiry."""
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, brand_guidelines FROM brands "
                    "WHERE is_active = true"
                )
            )
        ).fetchall()

        sent = 0
        for brand_id, name, guidelines in rows:
            g = guidelines
            if isinstance(g, str):
                try:
                    g = _json.loads(g)
                except (ValueError, TypeError):
                    continue
            if not isinstance(g, dict):
                continue

            li = (g.get("channels") or {}).get("linkedin") or {}
            if not li.get("enabled"):
                continue

            expiry, status = await _resolve_token_state(li)
            revoked = status is not None and status != "active"

            # Nothing to act on: no expiry known and token still active.
            if expiry is None and not revoked:
                continue
            # Active token still far from expiry → too early, skip.
            if (
                not revoked
                and expiry is not None
                and now < expiry - timedelta(days=_ALERT_WINDOW_DAYS)
            ):
                continue

            date_str = expiry.strftime("%b %d, %Y %H:%M UTC") if expiry else "unknown"
            if revoked or (expiry is not None and now >= expiry):
                title = f"LinkedIn token EXPIRED — {name}"
                body = (
                    f"Status: {status or 'expired'} (expiry {date_str}). "
                    "Reconnect LinkedIn now — publishing and analytics are interrupted."
                )
            else:
                days_left = max(0, (expiry - now).days)
                title = f"LinkedIn token expires in {days_left}d — {name}"
                body = (
                    f"Expires {date_str}. Reconnect LinkedIn to avoid an "
                    "interruption to publishing and analytics."
                )

            try:
                await notify_admins(
                    db=session,
                    notification_type="linkedin_token_expiry",
                    title=title,
                    body=body,
                    reference_type="brand",
                    reference_id=brand_id,
                    roles=("admin", "manager"),
                )
                sent += 1
            except Exception as exc:
                logger.warning(
                    "LinkedIn token alert failed for brand %s: %s", name, exc
                )

        if sent:
            logger.info("LinkedIn token expiry check: %d alert(s) sent", sent)
