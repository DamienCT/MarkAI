import json

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db

router = APIRouter()


@router.get("/")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT key, value FROM app_settings ORDER BY key")
    )
    rows = result.fetchall()
    return {row[0]: row[1] for row in rows}


@router.put("/")
async def update_settings(
    settings: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for key, value in settings.items():
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value, updated_by, updated_at) "
                "VALUES (:key, :value, :uid, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = :value, updated_by = :uid, updated_at = NOW()"
            ),
            {"key": key, "value": json.dumps(value), "uid": str(current_user.id)},
        )
    await db.commit()
    return {"status": "updated", "count": len(settings)}
