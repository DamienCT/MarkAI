import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db

router = APIRouter()

# Known setting keys from the app_settings table
_VALID_SETTING_KEYS = frozenset(
    {
        "scheduler_timezone",
        "morning_schedule_hour",
        "morning_schedule_minute",
        "publish_check_interval_minutes",
        "engagement_pull_interval_hours",
        "bc_sync_interval_hours",
        "max_daily_posts",
        "auto_approve_threshold",
        "default_channels",
        "notification_channels",
    }
)


class SettingsUpdate(BaseModel):
    """Typed model for settings update. Keys must be known setting names."""

    settings: dict[str, Any]

    @model_validator(mode="after")
    def validate_keys(self) -> "SettingsUpdate":
        unknown = set(self.settings.keys()) - _VALID_SETTING_KEYS
        if unknown:
            raise ValueError(
                f"Unknown setting key(s): {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(_VALID_SETTING_KEYS))}"
            )
        return self


@router.get("/")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(text("SELECT key, value FROM app_settings ORDER BY key"))
    rows = result.fetchall()
    return {row[0]: row[1] for row in rows}


@router.put("/")
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(
            status_code=403, detail="Admin role required to update settings"
        )
    for key, value in payload.settings.items():
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value, updated_by, updated_at) "
                "VALUES (:key, :value, :uid, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = :value, updated_by = :uid, updated_at = NOW()"
            ),
            {"key": key, "value": json.dumps(value), "uid": str(current_user.id)},
        )
    await db.commit()
    return {"status": "updated", "count": len(payload.settings)}
