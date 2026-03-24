"""Real Microsoft Teams webhook sender.

All functions POST actual payloads to the configured TEAMS_WEBHOOK_URL
using the MessageCard format.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("notifications.teams")


async def send_teams_message(
    title: str,
    text: str,
    color: str = "0076D7",
) -> None:
    """Send a MessageCard to Teams via incoming webhook."""
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": title,
        "sections": [
            {
                "activityTitle": title,
                "text": text,
                "markdown": True,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(settings.TEAMS_WEBHOOK_URL, json=payload)
        resp.raise_for_status()

    logger.info("Teams message sent: %s", title)


async def send_failure_alert(
    job_name: str,
    error: str,
    entity_info: str,
) -> None:
    """Send a formatted failure alert to Teams."""
    text = f"**Error:** {error}"
    if entity_info:
        text += f"\n\n**Context:** {entity_info}"

    await send_teams_message(
        title=f"Job Failed: {job_name}",
        text=text,
        color="FF0000",
    )


async def send_approval_notification(
    content_title: str,
    brand_name: str,
) -> None:
    """Send an approval-needed notification to Teams."""
    text = (
        f"**Content:** {content_title}\n\n"
        f"**Brand:** {brand_name}\n\n"
        f"Please review in the MARKAI portal."
    )
    await send_teams_message(
        title="Approval Needed",
        text=text,
    )
