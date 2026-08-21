import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.adaptation import Adaptation
from app.services import audit_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Statuses a human decision may act on. Everything else is already decided
# (applied/rejected) or a legacy terminal state — the transition is one-way.
_DECIDABLE_STATUSES = ("proposed", "auto_applied")


def _lift_notes(notes: str | None) -> dict:
    """Lift evaluation metadata JSON-encoded into adaptation_notes.

    Mirrors ``_lift_adaptation_row`` in agents/shared/tools/database.py: the
    adaptations table has no tier/confidence/data columns, so the evaluation
    workflow packs them into adaptation_notes as a JSON object. Malformed or
    legacy free-text notes never fail the listing — they default to tier 2
    (human review) at 0.5 confidence.
    """
    meta: dict = {}
    if isinstance(notes, str) and notes.lstrip().startswith("{"):
        try:
            parsed = json.loads(notes)
            if isinstance(parsed, dict):
                meta = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    try:
        tier = int(meta.get("tier", 2))
    except (TypeError, ValueError):
        tier = 2
    try:
        confidence = float(meta.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    data = meta.get("data", {})
    if isinstance(data, str):
        # historical rows double-encoded data as a JSON string
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "tier": tier if tier in (1, 2, 3) else 2,
        "confidence": confidence,
        "data": data,
    }


def _serialize(a: Adaptation) -> dict:
    return {
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
        **_lift_notes(a.adaptation_notes),
    }


@router.get("/adaptations")
async def list_adaptations(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all adaptations ordered by most recent, with pagination."""
    limit = min(limit, 200)
    stmt = (
        select(Adaptation)
        .order_by(Adaptation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(stmt)
    adaptations = result.scalars().all()

    return [_serialize(a) for a in adaptations]


class AdaptationDecision(BaseModel):
    action: Literal["apply", "reject"]
    note: str | None = None


@router.post("/adaptations/{adaptation_id}/decision")
async def decide_adaptation(
    adaptation_id: uuid.UUID,
    payload: AdaptationDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply or reject a proposed recommendation. Manager/admin only.

    The only human path from the recommendation queue to the legal
    'applied'/'rejected' statuses. Compare-and-set: a row may only leave
    'proposed'/'auto_applied' once — a second decision gets a 409. The
    acting user + note are recorded on the row's notes envelope and in
    the audit log.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Adaptation).where(Adaptation.id == adaptation_id)
    )
    adaptation = result.scalar_one_or_none()
    if adaptation is None:
        raise HTTPException(status_code=404, detail="Adaptation not found")
    old_status = adaptation.status
    if old_status not in _DECIDABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Adaptation already decided (status '{old_status}')",
        )

    new_status = "applied" if payload.action == "apply" else "rejected"

    # Record the decision inside the JSON notes envelope when the row has
    # one (evaluation rows) — tier/confidence/data keys stay intact for the
    # agents-side lift. Legacy free-text notes are left untouched; the audit
    # record below carries the actor + note regardless.
    new_notes = adaptation.adaptation_notes
    if isinstance(new_notes, str) and new_notes.lstrip().startswith("{"):
        try:
            parsed = json.loads(new_notes)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            parsed["decision"] = {
                "action": payload.action,
                "actor": current_user.email,
                "note": payload.note,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
            new_notes = json.dumps(parsed, default=str)

    # Compare-and-set on the status so a concurrent decision loses cleanly.
    updated = await db.execute(
        update(Adaptation)
        .where(
            Adaptation.id == adaptation_id,
            Adaptation.status.in_(_DECIDABLE_STATUSES),
        )
        .values(status=new_status, adaptation_notes=new_notes)
    )
    if (updated.rowcount or 0) == 0:
        raise HTTPException(status_code=409, detail="Adaptation already decided")
    await db.commit()

    await audit_service.record_audit(
        action=payload.action,
        entity_type="adaptation",
        entity_id=adaptation_id,
        user_id=current_user.id,
        old_values={"status": old_status},
        new_values={"status": new_status, "note": payload.note},
        request=request,
    )
    logger.info(
        "Adaptation %s %s by %s", adaptation_id, new_status, current_user.email
    )
    return {"id": str(adaptation_id), "status": new_status}
