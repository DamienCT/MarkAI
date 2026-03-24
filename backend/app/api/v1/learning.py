from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.models.adaptation import Adaptation

router = APIRouter()


@router.get("/adaptations")
async def list_adaptations(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all adaptations ordered by most recent, with pagination."""
    stmt = (
        select(Adaptation)
        .order_by(Adaptation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(stmt)
    adaptations = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "source_content_id": str(a.source_content_id),
            "target_channel": a.target_channel,
            "adapted_text": a.adapted_text,
            "adapted_headline": a.adapted_headline,
            "adapted_hashtags": a.adapted_hashtags,
            "adapted_media": a.adapted_media,
            "adaptation_notes": a.adaptation_notes,
            "ai_model": a.ai_model,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
        }
        for a in adaptations
    ]
