import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.config import settings
from app.deps import get_current_user, get_db
from app.models.brand import ALL_CHANNELS, CHANNEL_DISPLAY_NAMES
from app.models.competitor import Competitor
from app.schemas.brand import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    ChannelConfigUpdate,
)
from app.schemas.competitor import (
    CompetitorCreateBody,
    CompetitorResponse,
    CompetitorUpdate,
)
from app.services import audit_service, brand_service, fabric_service, minio_service
from app.utils.media_sign import media_response_headers, require_media_access
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

# Context-approvals gate: doc types that must be approved before content
# generation can run the first time on a brand. Each is a key under
# brand.brand_guidelines.context_approvals.
_CONTEXT_DOC_TYPES = ("research", "strategy", "planning", "calendar")

# Sensitive keys that must never leak to the frontend via brand_guidelines JSONB
_SENSITIVE_GUIDELINE_KEYS = {
    "access_token",
    "api_key",
    "refresh_token",
    "webhook_url",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "signing_key",
}

# Substring rule (N-02): legacy credential shapes use prefixed names
# (meta_access_token, linkedin_access_token, ...) that dodge the exact-name
# set above. Any key at any depth whose lowercase name CONTAINS one of these
# is stripped — including inside guidelines['social_credentials'].
_SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "client_secret",
)

# Regex for safe logo labels — alphanumeric, hyphens, underscores, max 50 chars
_SAFE_LABEL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


def _is_sensitive_key(key: object) -> bool:
    k = str(key).lower()
    if k in _SENSITIVE_GUIDELINE_KEYS:
        return True
    return any(s in k for s in _SENSITIVE_KEY_SUBSTRINGS)


def _strip_sensitive_recursive(obj: object) -> object:
    """Recursively strip sensitive keys from nested dicts."""
    if isinstance(obj, dict):
        return {
            k: _strip_sensitive_recursive(v)
            for k, v in obj.items()
            if not _is_sensitive_key(k)
        }
    if isinstance(obj, list):
        return [_strip_sensitive_recursive(item) for item in obj]
    return obj


def _strip_sensitive_guidelines(brand):
    """Return a brand object with sensitive fields removed from brand_guidelines.

    Works on a deep copy so the ORM instance is never mutated — prevents
    accidental persistence of stripped data via autoflush/commit.
    """
    from copy import deepcopy

    guidelines = brand.brand_guidelines
    if not guidelines or not isinstance(guidelines, dict):
        return brand
    cleaned = _strip_sensitive_recursive(deepcopy(guidelines))
    # Work on an expunged copy to prevent DB mutation
    brand_copy = deepcopy(brand)
    brand_copy.brand_guidelines = cleaned
    return brand_copy


def _maybe_strip_sensitive_guidelines(brand, user_role: str):
    """Strip sensitive fields unless the user is manager+ (who can edit them anyway).

    Manager+ has PUT /brands/{id}/channels write access. Returning unstripped data
    lets the UI keep the saved token in the form (with masked display + eye-toggle),
    so the user can review or replace it without the round-trip wiping the stored
    value. Viewer and editor cannot edit channels, so they still receive stripped
    data to enforce least-privilege.
    """
    if role_has_access(user_role, "manager"):
        return brand
    return _strip_sensitive_guidelines(brand)


@router.get("/bc-companies")
async def list_bc_companies(
    current_user: User = Depends(get_current_user),
):
    """Return distinct BC company names from the items table."""
    companies = await fabric_service.list_companies()
    return companies


@router.get("/bc-locations")
async def list_bc_locations(
    company: str,
    current_user: User = Depends(get_current_user),
):
    """Return distinct stock location codes for a given BC company."""
    locations = await fabric_service.list_locations_for_company(company)
    return locations


@router.get("/", response_model=list[BrandResponse])
async def list_brands(
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    brands = await brand_service.list_brands(
        db, is_active=is_active, skip=skip, limit=limit
    )
    return [_strip_sensitive_guidelines(b) for b in brands]


@router.get("/{brand_id}", response_model=BrandResponse)
async def get_brand(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return _maybe_strip_sensitive_guidelines(brand, current_user.role)


@router.post("/", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    data: BrandCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    existing = await brand_service.get_brand_by_slug(db, data.slug)
    if existing:
        raise HTTPException(status_code=409, detail="Brand slug already exists")
    # Force new brands to onboarding status
    data.is_active = False
    data.status = "onboarding"
    brand = await brand_service.create_brand(db, data)
    await audit_service.record_audit(
        action="create", entity_type="brand", user_id=current_user.id,
        entity_id=getattr(brand, "id", None),
        new_values={"name": data.name, "slug": data.slug},
        request=request,
    )
    return brand


@router.put("/{brand_id}", response_model=BrandResponse)
async def update_brand(
    brand_id: uuid.UUID,
    data: BrandUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # Sync is_active with status if status is provided
    if data.status is not None:
        data.is_active = data.status in ("active", "activating")
    elif data.is_active is not None:
        # Sync status with is_active if only is_active is provided
        if not data.is_active:
            data.status = "inactive"
    # Check if is_active is being set to false so we can cancel running agents
    deactivating = data.is_active is False

    try:
        brand = await brand_service.update_brand(db, brand_id, data)
        if brand is None:
            raise HTTPException(status_code=404, detail="Brand not found")

        # Cancel any running agent_runs when the brand is deactivated
        if deactivating:
            await db.execute(
                text(
                    "UPDATE agent_runs SET status = 'cancelled', completed_at = NOW() "
                    "WHERE brand_id = :brand_id AND status = 'running'"
                ),
                {"brand_id": brand_id},
            )
            await db.commit()

        await audit_service.record_audit(
            action="update", entity_type="brand", user_id=current_user.id,
            entity_id=brand_id,
            new_values={"status": data.status, "is_active": data.is_active},
            request=request,
        )
        return brand
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/{brand_id}/complete-onboarding", response_model=BrandResponse)
async def complete_onboarding(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate and mark onboarding as complete."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Validate required onboarding steps
    missing = []
    if not brand.name or not brand.description:
        missing.append("Brand name and description")
    if not brand.tone_of_voice:
        missing.append("Voice profile")

    # Check at least one channel enabled
    channels = (brand.brand_guidelines or {}).get("channels", {})
    has_channel = any(
        ch.get("enabled") for ch in channels.values() if isinstance(ch, dict)
    )
    if not has_channel:
        missing.append("At least one enabled channel")

    # Check at least one logo
    logos = (brand.brand_guidelines or {}).get("logos", {})
    if not logos:
        missing.append("At least one logo")

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Onboarding incomplete. Missing: {', '.join(missing)}",
        )

    from datetime import datetime, timezone

    brand.onboarding_completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.post("/{brand_id}/activate")
@_limiter.limit("5/minute")
async def activate_content_factory(
    request: Request,
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start Context Generation pipeline: research → strategy → plan → calendar."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    if not brand.onboarding_completed_at:
        raise HTTPException(status_code=422, detail="Complete onboarding first")

    if brand.status == "activating":
        # Allow re-activation if no agents are actually running (all failed/completed)
        running_check = await db.execute(
            text(
                "SELECT 1 FROM agent_runs WHERE brand_id = :bid AND status = 'running' LIMIT 1"
            ),
            {"bid": str(brand_id)},
        )
        if running_check.scalar_one_or_none():
            raise HTTPException(
                status_code=409, detail="Activation already in progress"
            )
        # All runs are done — allow re-activation by resetting status

    from datetime import datetime, timezone

    brand.status = "activating"
    brand.is_active = True
    brand.activation_started_at = datetime.now(timezone.utc)

    # First-time activation gate: if this brand has never passed the
    # context-approval gate, initialise per-doc approval state so the
    # frontend renders Approve/Rework buttons once context generation
    # completes. Brands that already passed (first_approval_completed=true)
    # keep that flag set — the gate disappears for the rest of their life.
    guidelines = dict(brand.brand_guidelines or {})
    if not guidelines.get("first_approval_completed"):
        guidelines["context_approvals"] = {doc: "pending" for doc in _CONTEXT_DOC_TYPES}
        guidelines["first_approval_completed"] = False
        from sqlalchemy.orm.attributes import flag_modified

        brand.brand_guidelines = guidelines
        flag_modified(brand, "brand_guidelines")

    await db.commit()

    # Trigger the research pipeline (worker chains: research → strategy → planning → content)
    from app.services import nats_service

    # Full-year calendar: planning batches run in parallel (semaphore=8)
    # so the full 52-week generation completes in ~5 min, not ~36 min.
    await nats_service.publish(
        "research.trigger",
        {
            "brand_id": str(brand_id),
            "trigger": "activation",
            "scope_weeks": 52,
        },
    )

    return {
        "status": "activating",
        "brand_id": str(brand_id),
        "message": "Context Generation started. Research → Strategy → Plan → Calendar.",
    }


@router.post("/{brand_id}/generate-content")
@_limiter.limit("5/minute")
async def generate_content(
    request: Request,
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger content generation for queued calendar items."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # First-time approval gate: block content generation until all 4 context
    # documents are approved. Brands that have already passed this gate
    # (first_approval_completed=true) or that pre-date the feature
    # (context_approvals field absent) bypass the check.
    guidelines = brand.brand_guidelines or {}
    approvals = guidelines.get("context_approvals")
    if isinstance(approvals, dict) and not guidelines.get("first_approval_completed"):
        unapproved = [d for d in _CONTEXT_DOC_TYPES if approvals.get(d) != "approved"]
        if unapproved:
            raise HTTPException(
                status_code=403,
                detail=(
                    "You must review and approve all 4 context reports "
                    "before generating content. Missing: "
                    f"{', '.join(unapproved)}"
                ),
            )

    # Verify context generation completed
    ctx_check = await db.execute(
        text(
            "SELECT agent_type FROM agent_runs "
            "WHERE brand_id = :bid AND status = 'completed' "
            "AND agent_type IN ('research', 'strategy', 'planning') "
            "GROUP BY agent_type"
        ),
        {"bid": str(brand_id)},
    )
    completed_types = {row[0] for row in ctx_check.fetchall()}
    missing = {"research", "strategy", "planning"} - completed_types
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Run Context Generation first. Missing: {', '.join(sorted(missing))}",
        )

    # Query calendar items within TODAY + N days that need content generation.
    # N comes from the content_generation_days_ahead setting (default 14) — same
    # window the auto top-up job uses, so the button and the scheduler agree.
    from datetime import datetime, timedelta, timezone

    from app.scheduler import get_app_setting

    try:
        days_ahead = int(await get_app_setting("content_generation_days_ahead", default=14))
    except (TypeError, ValueError):
        days_ahead = 14

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)

    items_result = await db.execute(
        text(
            "SELECT id FROM calendar_items "
            "WHERE brand_id = :bid AND status IN ('queued', 'planned') "
            "  AND scheduled_at IS NOT NULL "
            "  AND scheduled_at BETWEEN :now AND :horizon "
            "ORDER BY scheduled_at ASC"
        ),
        {"bid": str(brand_id), "now": now, "horizon": horizon},
    )
    item_ids = [str(row[0]) for row in items_result.fetchall()]

    if not item_ids:
        return {
            "status": "no_items",
            "items_queued": 0,
            "brand_id": str(brand_id),
            "message": f"No calendar items need content generation in the next {days_ahead} days.",
        }

    # Transition planned items to queued so they appear in Content Studio
    await db.execute(
        text(
            "UPDATE calendar_items SET status = 'queued' "
            "WHERE id = ANY(:ids) AND status = 'planned'"
        ),
        {"ids": item_ids},
    )
    await db.commit()

    # Publish first item with remaining_queue for sequential processing
    from app.services import nats_service

    first_id = item_ids[0]
    remaining = item_ids[1:]

    await nats_service.publish(
        "content.generate",
        {
            "brand_id": str(brand_id),
            "calendar_item_id": first_id,
            "trigger": "manual",
            "remaining_queue": remaining,
        },
    )

    return {
        "status": "generating",
        "items_queued": len(item_ids),
        "brand_id": str(brand_id),
        "message": f"Content generation started for {len(item_ids)} items ({now.strftime('%b %d')} – {horizon.strftime('%b %d')}).",
    }


# ──────────────────────────────────────────────────────────────────────
# Document overrides ("Edit Documents") — durable editable levers.
# Stored under brand.brand_guidelines.overrides (JSONB → no migration) and
# read with PRIORITY by the planning/content workflows.
# ──────────────────────────────────────────────────────────────────────


class BrandOverrides(BaseModel):
    """Editable levers that override the auto-generated strategy/plan."""

    cadence: dict | None = None  # {channel: {posts_per_week, best_days}}
    content_pillars: list[str] | None = None
    target_audiences: list[dict] | None = None
    content_format: str | None = None  # "posts_only" | "mixed"
    brand_voice: str | None = None
    positioning: str | None = None  # brand positioning statement
    monthly_themes: list | None = None  # [{month, theme}] or [str]
    campaigns: list[dict] | None = None  # user-curated campaigns (name/description)
    removed_campaigns: list[str] | None = None


class ApplyOverrides(BaseModel):
    """Optional body for the apply (re-plan) endpoint.

    `months` is a list of "Month YYYY" or "YYYY-MM" strings — when present, the
    re-plan is TARGETED to only those calendar months (the ones the user
    changed). Empty/absent → full-horizon re-plan (legacy behavior).
    """

    months: list[str] | None = None


_MONTH_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _to_year_month(label: str) -> str | None:
    """Normalize 'August 2026' or '2026-08' → '2026-08'. None if unparseable."""
    s = (label or "").strip()
    if not s:
        return None
    # Already YYYY-MM(-...) ?
    parts = s.replace("/", "-").split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        y, mo = int(parts[0]), int(parts[1])
        if 1 <= mo <= 12 and y >= 2000:
            return f"{y:04d}-{mo:02d}"
    # "Month YYYY" form
    tokens = s.replace(",", " ").split()
    month = year = None
    for t in tokens:
        tl = t.lower()
        if tl in _MONTH_NUM:
            month = _MONTH_NUM[tl]
        elif t.isdigit() and len(t) == 4:
            year = int(t)
    if month and year:
        return f"{year:04d}-{month:02d}"
    return None


async def _latest_run_payload(db: AsyncSession, brand_id: uuid.UUID, agent_type: str) -> dict:
    """Latest completed agent_run output_payload for a brand/type (dict, never raises)."""
    import json as _json

    row = (
        await db.execute(
            text(
                "SELECT output_payload FROM agent_runs "
                "WHERE brand_id = :bid AND agent_type = :t AND status = 'completed' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"bid": str(brand_id), "t": agent_type},
        )
    ).fetchone()
    payload = row[0] if row else None
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except (ValueError, TypeError):
            return {}
    return payload if isinstance(payload, dict) else {}


async def _recent_run_payloads(
    db: AsyncSession, brand_id: uuid.UUID, agent_type: str, limit: int = 8
) -> list[dict]:
    """Recent completed run payloads for a brand/type, newest first (dicts).

    A single strategy generation can produce two runs with different key
    conventions (workflow run: pillars/audiences/cadence/themes; store_strategy
    run: content_pillars/target_audiences/posting_cadence/monthly_themes), and a
    field present in one may be empty in the other. Callers merge per-field.
    """
    import json as _json

    rows = (
        await db.execute(
            text(
                "SELECT output_payload FROM agent_runs "
                "WHERE brand_id = :bid AND agent_type = :t AND status = 'completed' "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"bid": str(brand_id), "t": agent_type, "lim": limit},
        )
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        p = r[0]
        if isinstance(p, str):
            try:
                p = _json.loads(p)
            except (ValueError, TypeError):
                continue
        if isinstance(p, dict):
            out.append(p)
    return out


def _guidelines_dict(brand) -> dict:
    import json as _json

    g = brand.brand_guidelines or {}
    if isinstance(g, str):
        try:
            g = _json.loads(g)
        except (ValueError, TypeError):
            g = {}
    return g if isinstance(g, dict) else {}


@router.get("/{brand_id}/overrides")
async def get_brand_overrides(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the editable levers for the Edit Documents modal — saved overrides
    merged over the current auto-generated values (for pre-fill)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = _guidelines_dict(brand)
    saved = guidelines.get("overrides") or {}

    # A single strategy generation can produce two runs with different key
    # conventions, and a field present in one may be empty in the other
    # (e.g. one run has pillars/audiences, another has the monthly themes).
    # Pick each field from the newest recent run that actually has it.
    strat_runs = await _recent_run_payloads(db, brand_id, "strategy")
    plan = await _latest_run_payload(db, brand_id, "planning")

    def _pick(*keys):
        """First non-empty value for any of `keys`, scanning runs newest-first."""
        for run in strat_runs:
            for k in keys:
                v = run.get(k)
                if v:
                    return v
        return None

    raw_pillars = _pick("content_pillars", "pillars") or []
    cur_pillars = [
        (p.get("name") if isinstance(p, dict) else p) for p in raw_pillars
    ]
    removed = set(saved.get("removed_campaigns") or [])

    # Audiences → normalize to {name, description} (key may be name/segment_name).
    def _aud_obj(a):
        if isinstance(a, dict):
            name = a.get("name") or a.get("segment_name") or a.get("persona_ref") or ""
            return {"name": name, "description": a.get("description") or ""}
        return {"name": str(a), "description": ""}

    raw_audiences = saved.get("target_audiences") or _pick("target_audiences", "audiences") or []
    audiences = [a for a in (_aud_obj(a) for a in raw_audiences) if a["name"]]

    # Campaigns as {name, description} objects. Saved user-curated list wins;
    # otherwise derive from the latest plan, minus any removed by name.
    def _camp_obj(c):
        if isinstance(c, dict):
            return {"name": c.get("name") or "", "description": c.get("description") or ""}
        return {"name": str(c), "description": ""}

    if saved.get("campaigns"):
        campaigns = [_camp_obj(c) for c in saved["campaigns"]]
    else:
        campaigns = [
            _camp_obj(c)
            for c in (plan.get("campaigns") or [])
            if (c.get("name") if isinstance(c, dict) else c) not in removed
        ]
        campaigns = [c for c in campaigns if c["name"]]

    pos = _pick("positioning")
    positioning = (
        pos if isinstance(pos, str)
        else (pos or {}).get("value_proposition", "") if isinstance(pos, dict)
        else ""
    )

    return {
        "cadence": saved.get("cadence") or _pick("cadence", "posting_cadence") or {},
        "content_pillars": saved.get("content_pillars") or [p for p in cur_pillars if p],
        "target_audiences": audiences,
        "campaigns": campaigns,
        "removed_campaigns": sorted(removed),
        "positioning": saved.get("positioning") or positioning,
        "monthly_themes": saved.get("monthly_themes") or _pick("monthly_themes", "themes") or [],
        "content_format": saved.get("content_format") or "posts_only",
        "brand_voice": saved.get("brand_voice") or guidelines.get("tone_of_voice") or "",
        "has_overrides": bool(saved),
    }


@router.put("/{brand_id}/overrides")
async def save_brand_overrides(
    brand_id: uuid.UUID,
    body: BrandOverrides,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist edited levers into brand_guidelines.overrides (no re-plan)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    from sqlalchemy.orm.attributes import flag_modified

    guidelines = _guidelines_dict(brand)
    overrides = dict(guidelines.get("overrides") or {})
    data = body.model_dump(exclude_none=True)
    overrides.update(data)
    guidelines["overrides"] = overrides
    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()

    await audit_service.record_audit(
        action="update",
        entity_type="brand",
        user_id=current_user.id,
        entity_id=brand_id,
        new_values={"overrides": sorted(data.keys())},
        request=request,
    )
    return {"status": "saved", "overrides": overrides}


@router.post("/{brand_id}/overrides/apply")
async def apply_brand_overrides(
    brand_id: uuid.UUID,
    body: ApplyOverrides | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run planning so the saved overrides take effect on the calendar.

    Planning preserves anything already moved forward (in_review/published/…);
    only `planned` items are rebuilt. When `body.months` is provided the re-plan
    is TARGETED to just those months (only their planned items are rebuilt);
    otherwise the full horizon is re-planned.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    target_months = []
    for label in (body.months if body and body.months else []):
        ym = _to_year_month(label)
        if ym and ym not in target_months:
            target_months.append(ym)

    from app.services import nats_service

    msg = {"brand_id": str(brand_id), "trigger": "manual", "triggered_by": str(current_user.id)}
    if target_months:
        msg["target_months"] = target_months

    await nats_service.publish("planning.trigger", msg)
    return {
        "status": "re-planning",
        "brand_id": str(brand_id),
        "target_months": target_months,
        "scope": "targeted" if target_months else "full",
    }


class ThemeRefineRequest(BaseModel):
    """Body for the AI theme-refinement endpoint (the 'wand' button)."""

    text: str
    month: str | None = None


@router.post("/{brand_id}/themes/refine")
async def refine_monthly_theme(
    brand_id: uuid.UUID,
    body: ThemeRefineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reformulate a user's rough monthly-theme note into a crisp, planning-ready
    theme statement, grounded in the brand's positioning."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    raw = (body.text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Theme text is required")

    from app.api.v1.intelligence import _call_llm

    brand_ctx = f"Brand: {brand.name}."
    if getattr(brand, "description", None):
        brand_ctx += f" {brand.description[:500]}"
    month_ctx = f" The theme is for {body.month}." if body.month else ""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a content strategist. Rewrite the user's rough monthly content "
                "theme into ONE concise, vivid theme statement (max ~30 words) that a content "
                "planner can act on: a clear seasonal/commercial angle and what to emphasize. "
                "Keep the user's intent. Return ONLY the rewritten theme text — no quotes, "
                "no preamble, no markdown."
            ),
        },
        {
            "role": "user",
            "content": f"{brand_ctx}{month_ctx}\n\nRough theme: {raw}",
        },
    ]
    try:
        refined = (await _call_llm(messages, temperature=0.6)).strip()
    except Exception as exc:
        logger.warning("Theme refine failed for brand %s: %s", brand_id, exc)
        raise HTTPException(status_code=502, detail="AI refinement unavailable, try again")

    refined = refined.strip().strip('"').strip()
    return {"theme": refined or raw}


class ContextApprovalAction(BaseModel):
    """Request body for the context-approval endpoint."""

    action: Literal["approve", "reset"]


@router.post("/{brand_id}/context-approvals/{doc_type}", response_model=BrandResponse)
async def update_context_approval(
    brand_id: uuid.UUID,
    doc_type: str,
    body: ContextApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or reset (Rework) a single context document.

    Approve flips that doc's status from 'pending' to 'approved' and, when
    all four documents are approved, sets first_approval_completed=true so
    the gate disappears permanently for this brand.

    Reset flips it back to 'pending' and is called by the frontend when the
    user clicks Rework — paired with the existing regenerate trigger so the
    user has to re-approve the regenerated document.

    Once first_approval_completed is true, the endpoint refuses further
    changes: the buttons no longer exist in the UI and the gate is closed
    for life on this brand.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if doc_type not in _CONTEXT_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown doc_type '{doc_type}'. Allowed: {', '.join(_CONTEXT_DOC_TYPES)}",
        )

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    if guidelines.get("first_approval_completed"):
        raise HTTPException(
            status_code=409,
            detail="Context already approved for this brand. The approval gate is closed.",
        )

    approvals = dict(guidelines.get("context_approvals") or {})
    # Lazy-init missing entries so a brand activated before the feature
    # rollout doesn't error out on the first approve call.
    for d in _CONTEXT_DOC_TYPES:
        approvals.setdefault(d, "pending")

    if body.action == "approve":
        approvals[doc_type] = "approved"
    else:  # reset
        approvals[doc_type] = "pending"

    guidelines = dict(guidelines)
    guidelines["context_approvals"] = approvals
    if all(approvals.get(d) == "approved" for d in _CONTEXT_DOC_TYPES):
        guidelines["first_approval_completed"] = True
    else:
        guidelines["first_approval_completed"] = False

    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return brand


@router.get("/{brand_id}/channels")
async def get_brand_channels(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return channel config for a brand with setup status."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    channels = guidelines.get("channels", {})

    result = []
    for ch in ALL_CHANNELS:
        cfg = channels.get(ch, {})
        result.append(
            {
                "channel": ch,
                "enabled": cfg.get("enabled", False),
                "configured": cfg.get("configured", False),
                "display_name": CHANNEL_DISPLAY_NAMES[ch],
                "requires_setup": ch not in ["website_blog", "teams"],
            }
        )
    return result


@router.get("/{brand_id}/channels/linkedin/token-status")
async def linkedin_token_status(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live LinkedIn token expiry/status via introspection (stored field fallback)."""
    from datetime import datetime, timezone

    from app.scheduler.linkedin_token_alert import _resolve_token_state

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    li = ((brand.brand_guidelines or {}).get("channels") or {}).get("linkedin") or {}
    if not li.get("enabled"):
        return {"enabled": False, "expires_at": None, "status": None,
                "days_left": None, "source": None}

    expiry, status = await _resolve_token_state(li)
    days_left = (
        (expiry - datetime.now(timezone.utc)).days if expiry is not None else None
    )
    source = (
        "introspection" if status is not None
        else ("manual" if li.get("token_expires_at") else None)
    )
    return {
        "enabled": True,
        "expires_at": expiry.isoformat() if expiry else None,
        "status": status,
        "days_left": days_left,
        "source": source,
    }


@router.put("/{brand_id}/channels")
async def update_brand_channels(
    brand_id: uuid.UUID,
    data: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update channel configuration for a brand."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = dict(brand.brand_guidelines or {})
    guidelines["channels"] = data.channels

    # Direct update with flag_modified to ensure JSONB persistence
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)

    return {"status": "ok", "channels": brand.brand_guidelines.get("channels", {})}


@router.post("/{brand_id}/logos")
async def upload_brand_logo(
    brand_id: uuid.UUID,
    file: UploadFile = File(...),
    label: str = "primary",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a brand logo. Supports multiple logos with labels (primary, icon, watermark, etc.)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Validate label to prevent path traversal in MinIO object names
    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(
            status_code=400,
            detail="Invalid label — use only alphanumeric characters, hyphens, and underscores (max 50 chars)",
        )

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Validate file type (SVG excluded to prevent stored XSS)
    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    # Read file and upload to MinIO
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate magic bytes match declared content type
    _magic_ok = False
    if data[:4] == b"\x89PNG" and file.content_type == "image/png":
        _magic_ok = True
    elif data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg":
        _magic_ok = True
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and file.content_type == "image/webp":
        _magic_ok = True
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else "png"
    )
    object_name = f"brands/{brand_id}/logos/{label}.{ext}"

    await minio_service.ensure_bucket()
    await minio_service.upload_file(
        object_name, data, content_type=file.content_type or "image/png"
    )

    # Generate URL and update brand
    logo_url = f"/api/v1/brands/{brand_id}/logos/{label}"

    # Store logo info in brand_guidelines
    guidelines = dict(brand.brand_guidelines or {})
    logos = guidelines.get("logos", {})
    logos[label] = {
        "object_name": object_name,
        "url": logo_url,
        "content_type": file.content_type,
        "filename": file.filename,
    }
    guidelines["logos"] = logos

    # Direct update with flag_modified for JSONB persistence
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = guidelines
    if label == "primary":
        brand.logo_url = logo_url
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok", "label": label, "url": logo_url, "logos": logos}


@router.get("/{brand_id}/logos/{label}")
async def get_brand_logo(
    brand_id: uuid.UUID,
    label: str,
    db: AsyncSession = Depends(get_db),
    _media_auth: None = Depends(require_media_access),
):
    """Serve a brand logo by label.

    Requires media auth (Entra bearer, X-Media-Token, or signed mt/exp) —
    browser <img> tags load this through the frontend's same-origin
    /api/media proxy, which injects the token after a session check.
    """
    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="Invalid label")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    logos = guidelines.get("logos", {})
    logo_info = logos.get(label)
    if not logo_info:
        raise HTTPException(status_code=404, detail="Logo not found")

    try:
        data = await minio_service.download_file(logo_info["object_name"])
    except Exception:
        raise HTTPException(status_code=404, detail="Logo file not found in storage")

    from fastapi.responses import Response

    media_type = logo_info.get("content_type", "image/png")
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=86400",
            **media_response_headers(media_type),
        },
    )


@router.delete("/{brand_id}/logos/{label}")
async def delete_brand_logo(
    brand_id: uuid.UUID,
    label: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a brand logo."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="Invalid label")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = dict(brand.brand_guidelines or {})
    logos = guidelines.get("logos", {})
    logo_info = logos.pop(label, None)
    if not logo_info:
        raise HTTPException(status_code=404, detail="Logo not found")

    try:
        await minio_service.delete_file(logo_info["object_name"])
    except Exception:
        pass  # File may already be deleted

    guidelines["logos"] = logos

    # Force SQLAlchemy to detect the JSONB change by assigning a new dict
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = dict(guidelines)
    if label == "primary":
        brand.logo_url = None
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok"}


# ── Vendor (manufacturer) logos ─────────────────────────────────────
# A logo belongs to a *vendor*, not a product: it is keyed by the product's
# exact ``vendor_name`` and stored in ``brand_guidelines.vendor_logos`` (JSONB,
# no migration). One logo therefore covers every product of that manufacturer.

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _vendor_slug(vendor_name: str) -> str:
    """URL/object-safe slug for a vendor name (used as the MinIO filename)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (vendor_name or "").lower()).strip("-")
    return (slug or "vendor")[:60]


# A vendor can have two logo variants: "light" (primary — for white/light
# backgrounds) and "dark" (secondary — for dark backgrounds). Stored nested:
#   vendor_logos[name] = {"light": {entry}, "dark": {entry}}
# Legacy single-logo entries (a flat {object_name, ...}) are read as "light"
# so pre-existing logos keep working without a migration.
_VENDOR_VARIANTS = ("light", "dark")


def _vendor_variants(value) -> dict:
    """Normalize a stored vendor_logos[name] value to {variant: entry}."""
    if not isinstance(value, dict):
        return {}
    if value.get("object_name"):  # legacy flat single → treat as light
        return {"light": value}
    out = {}
    for v in _VENDOR_VARIANTS:
        entry = value.get(v)
        if isinstance(entry, dict) and entry.get("object_name"):
            out[v] = entry
    return out


def _ext_for_content_type(ct: str) -> str:
    ct = (ct or "").lower()
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    return "jpg"


def _looks_like_svg(data: bytes) -> bool:
    """Sniff markup (SVG/XML/HTML) regardless of the declared content type.

    No real raster format starts with '<' after leading whitespace, so this
    never false-positives on a genuine image.
    """
    return data[:512].lstrip().startswith(b"<")


def _clean_logo_bytes(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Trim a vendor logo to its content so the editor and the rendered post
    show it at the SAME size: key out a near-white background (web logos are
    often opaque JPEG/PNG on a white card) and crop to the tight bounding box,
    returning a transparent PNG. This mirrors what the PIL renderer does at
    draw time — doing it once at storage keeps the editor's raw <img> and the
    render identical. Undecodable (non-SVG) images are returned untouched.

    SVG is REJECTED outright (415): it is active content, the upload
    endpoints already ban it, and letting the fetch path store it created a
    stored-XSS route through the /files proxy (audit P0-08 / addendum §2.4).
    """
    if "svg" in (content_type or "").lower() or _looks_like_svg(data):
        raise HTTPException(
            status_code=415, detail="SVG logos are not supported"
        )
    try:
        from io import BytesIO

        from PIL import Image, ImageChops

        img = Image.open(BytesIO(data)).convert("RGBA")
        # Opaque source → key out the near-white background (>=245 on all
        # channels), but never if the whole image is white.
        if img.getchannel("A").getextrema()[0] >= 250:
            r, g, b = img.convert("RGB").split()

            def _thr(c):
                return c.point(lambda v: 255 if v >= 245 else 0)

            white = ImageChops.multiply(ImageChops.multiply(_thr(r), _thr(g)), _thr(b))
            lo, hi = white.getextrema()
            if hi == 255 and lo != 255:
                img.putalpha(white.point(lambda v: 0 if v >= 128 else 255))
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        out = BytesIO()
        img.save(out, format="PNG")
        return out.getvalue(), "image/png"
    except Exception as exc:
        logger.warning("Vendor logo cleanup failed, storing as-is: %s", exc)
        return data, content_type


async def _store_logo(
    db: AsyncSession,
    brand,
    key: str,
    image_data: bytes,
    content_type: str,
    source_url: str | None,
    *,
    variant: str,
    dict_name: str,
    path_prefix: str,
) -> dict:
    """Upload a logo to MinIO and record it under brand_guidelines[dict_name][key].

    Generic over the keying dimension: ``dict_name="vendor_logos"`` keyed by
    vendor name, or ``dict_name="category_logos"`` keyed by category code. Stored
    per variant ("light" / "dark") so the renderer can pick the right one for the
    background. Migrates any legacy flat entry into the variant map.
    """
    variant = variant if variant in _VENDOR_VARIANTS else "light"
    # Trim to content (white-key + crop) so editor and render match in size.
    image_data, content_type = _clean_logo_bytes(image_data, content_type)
    slug = _vendor_slug(key)
    ext = _ext_for_content_type(content_type)
    object_name = f"brands/{brand.id}/{path_prefix}/{slug}-{variant}.{ext}"

    await minio_service.ensure_bucket()
    await minio_service.upload_file(object_name, image_data, content_type or "image/png")

    from sqlalchemy.orm.attributes import flag_modified

    guidelines = dict(brand.brand_guidelines or {})
    logos = dict(guidelines.get(dict_name, {}))
    entry = {
        "object_name": object_name,
        "url": object_name,  # served via the /files proxy (fileUrl on frontend)
        "content_type": content_type or "image/png",
        "slug": slug,
        "source_url": source_url,
    }
    # Normalize the existing value (legacy flat → {"light": ...}) then set ours.
    variants = _vendor_variants(logos.get(key))
    variants[variant] = entry
    logos[key] = variants
    guidelines[dict_name] = logos
    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return entry


async def _store_vendor_logo(
    db: AsyncSession,
    brand,
    vendor_name: str,
    image_data: bytes,
    content_type: str,
    source_url: str | None,
    variant: str = "light",
) -> dict:
    return await _store_logo(
        db, brand, vendor_name, image_data, content_type, source_url,
        variant=variant, dict_name="vendor_logos", path_prefix="vendor-logos",
    )


async def _store_category_logo(
    db: AsyncSession,
    brand,
    category: str,
    image_data: bytes,
    content_type: str,
    source_url: str | None,
    variant: str = "light",
) -> dict:
    return await _store_logo(
        db, brand, category, image_data, content_type, source_url,
        variant=variant, dict_name="category_logos", path_prefix="category-logos",
    )


class VendorLogoFetch(BaseModel):
    vendor_name: str
    attempt: int = 0  # increments to cycle through alternative Bing candidates
    variant: str = "light"  # "light" (white bg) | "dark" (dark bg)


class CategoryLogoFetch(BaseModel):
    category: str
    attempt: int = 0  # increments to cycle through alternative Bing candidates
    variant: str = "light"  # "light" (white bg) | "dark" (dark bg)


@router.get("/{brand_id}/vendors")
async def list_brand_vendors(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the distinct vendors present in the brand's synced products, each
    with its current logo (if any). New vendors appear automatically after a
    product sync — the list is derived, never stored."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    rows = await db.execute(
        text(
            "SELECT DISTINCT vendor_name FROM products "
            "WHERE brand_id = :bid AND vendor_name IS NOT NULL "
            "AND vendor_name <> '' ORDER BY vendor_name"
        ),
        {"bid": str(brand_id)},
    )
    names = [r[0] for r in rows.fetchall()]

    vendor_logos = (brand.brand_guidelines or {}).get("vendor_logos", {})
    vendors = []
    for name in names:
        variants = _vendor_variants(vendor_logos.get(name))
        light = (variants.get("light") or {}).get("object_name")
        dark = (variants.get("dark") or {}).get("object_name")
        vendors.append(
            {
                "vendor_name": name,
                "has_logo": bool(light or dark),
                # Back-compat: logo_url is the primary (light) or whichever exists.
                "logo_url": light or dark,
                "light_url": light,
                "dark_url": dark,
            }
        )
    return {"vendors": vendors}


@router.post("/{brand_id}/vendors/fetch-logo")
async def fetch_vendor_logo(
    brand_id: uuid.UUID,
    body: VendorLogoFetch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search Bing (via the browser worker) for the vendor's logo and store it.
    Pass an incrementing ``attempt`` to cycle through alternative candidates."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    vendor = (body.vendor_name or "").strip()
    if not vendor:
        raise HTTPException(status_code=400, detail="vendor_name is required")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    import httpx

    logo_url: str | None = None
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{settings.BROWSER_WORKER_URL}/capture/logo",
                json={"vendor_name": vendor, "offset": max(0, body.attempt)},
                headers={
                    "X-API-Key": getattr(settings, "BROWSER_WORKER_API_KEY", "")
                    or "internal"
                },
            )
            resp.raise_for_status()
            logo_url = (resp.json() or {}).get("image_url")
    except Exception as exc:
        logger.warning("Bing logo search failed for '%s': %s", vendor, exc)
        raise HTTPException(status_code=502, detail="Logo search failed") from exc

    if not logo_url:
        raise HTTPException(status_code=404, detail="No logo found for this vendor")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            dl = await client.get(logo_url, headers={"User-Agent": _UA})
        if dl.status_code != 200 or not dl.content:
            raise HTTPException(status_code=404, detail="Logo could not be downloaded")
        ct = dl.headers.get("content-type", "image/png").split(";")[0].strip().lower()
        # SVG is active content — the fetch path must match the upload
        # paths' ban (stored XSS served back through the /files proxy).
        if not ct.startswith("image/") or "svg" in ct:
            raise HTTPException(
                status_code=415, detail="Result was not a supported image"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to download logo from %s: %s", logo_url, exc)
        raise HTTPException(status_code=502, detail="Logo download failed") from exc

    entry = await _store_vendor_logo(
        db, brand, vendor, dl.content, ct, logo_url, variant=body.variant
    )
    logger.info(
        "Stored vendor logo for '%s' variant=%s (brand %s)", vendor, body.variant, brand_id
    )
    return {
        "status": "ok",
        "vendor_name": vendor,
        "logo_url": entry["object_name"],
        "variant": body.variant,
        "attempt": body.attempt,
    }


@router.post("/{brand_id}/vendors/upload-logo")
async def upload_vendor_logo(
    brand_id: uuid.UUID,
    vendor_name: str,
    variant: str = "light",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually upload a vendor's logo (overrides the Bing search result)."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    vendor = (vendor_name or "").strip()
    if not vendor:
        raise HTTPException(status_code=400, detail="vendor_name is required")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    _magic_ok = (
        (data[:4] == b"\x89PNG" and file.content_type == "image/png")
        or (data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg")
        or (
            data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
            and file.content_type == "image/webp"
        )
    )
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    entry = await _store_vendor_logo(
        db, brand, vendor, data, file.content_type or "image/png", None, variant=variant
    )
    return {
        "status": "ok",
        "vendor_name": vendor,
        "logo_url": entry["object_name"],
        "variant": variant if variant in _VENDOR_VARIANTS else "light",
    }


@router.delete("/{brand_id}/vendors/logo")
async def delete_vendor_logo(
    brand_id: uuid.UUID,
    vendor_name: str,
    variant: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a vendor's stored logo. Pass ``variant`` to remove just one
    variant ("light"/"dark"); omit it to remove all of the vendor's logos."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    from sqlalchemy.orm.attributes import flag_modified

    guidelines = dict(brand.brand_guidelines or {})
    vendor_logos = dict(guidelines.get("vendor_logos", {}))
    variants = _vendor_variants(vendor_logos.get(vendor_name))
    if not variants:
        raise HTTPException(status_code=404, detail="Vendor logo not found")

    to_delete = (
        [variant] if variant in _VENDOR_VARIANTS else list(variants.keys())
    )
    removed_any = False
    for v in to_delete:
        entry = variants.pop(v, None)
        if entry and entry.get("object_name"):
            removed_any = True
            try:
                await minio_service.delete_file(entry["object_name"])
            except Exception:
                pass
    if not removed_any:
        raise HTTPException(status_code=404, detail="Vendor logo not found")

    if variants:
        vendor_logos[vendor_name] = variants
    else:
        vendor_logos.pop(vendor_name, None)
    guidelines["vendor_logos"] = vendor_logos
    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok"}


# ── Category logos ──────────────────────────────────────────────────
# Same mechanism as vendor logos, but keyed by the product's category code
# (itemCategoryCode, e.g. "REUS-WEAR"). Used as a FALLBACK at render time when a
# product has no vendor logo (e.g. wearables with a blank/blocked vendor).
# Stored in brand_guidelines.category_logos[category] = {"light":…, "dark":…}.


@router.get("/{brand_id}/categories")
async def list_brand_categories(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the distinct categories present in the brand's synced products, each
    with its current logo (if any). Derived from the products table, never stored."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    rows = await db.execute(
        text(
            "SELECT DISTINCT category FROM products "
            "WHERE brand_id = :bid AND category IS NOT NULL "
            "AND category <> '' ORDER BY category"
        ),
        {"bid": str(brand_id)},
    )
    names = [r[0] for r in rows.fetchall()]

    category_logos = (brand.brand_guidelines or {}).get("category_logos", {})
    categories = []
    for name in names:
        variants = _vendor_variants(category_logos.get(name))
        light = (variants.get("light") or {}).get("object_name")
        dark = (variants.get("dark") or {}).get("object_name")
        categories.append(
            {
                "category": name,
                "has_logo": bool(light or dark),
                "logo_url": light or dark,
                "light_url": light,
                "dark_url": dark,
            }
        )
    return {"categories": categories}


@router.post("/{brand_id}/categories/fetch-logo")
async def fetch_category_logo(
    brand_id: uuid.UUID,
    body: CategoryLogoFetch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search the web (via the browser worker) for a logo for this category and
    store it. Pass an incrementing ``attempt`` to cycle through candidates."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    category = (body.category or "").strip()
    if not category:
        raise HTTPException(status_code=400, detail="category is required")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    import httpx

    logo_url: str | None = None
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{settings.BROWSER_WORKER_URL}/capture/logo",
                json={"vendor_name": category, "offset": max(0, body.attempt)},
                headers={
                    "X-API-Key": getattr(settings, "BROWSER_WORKER_API_KEY", "")
                    or "internal"
                },
            )
            resp.raise_for_status()
            logo_url = (resp.json() or {}).get("image_url")
    except Exception as exc:
        logger.warning("Logo search failed for category '%s': %s", category, exc)
        raise HTTPException(status_code=502, detail="Logo search failed") from exc

    if not logo_url:
        raise HTTPException(status_code=404, detail="No logo found for this category")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            dl = await client.get(logo_url, headers={"User-Agent": _UA})
        if dl.status_code != 200 or not dl.content:
            raise HTTPException(status_code=404, detail="Logo could not be downloaded")
        ct = dl.headers.get("content-type", "image/png").split(";")[0].strip().lower()
        # SVG is active content — the fetch path must match the upload
        # paths' ban (stored XSS served back through the /files proxy).
        if not ct.startswith("image/") or "svg" in ct:
            raise HTTPException(
                status_code=415, detail="Result was not a supported image"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to download logo from %s: %s", logo_url, exc)
        raise HTTPException(status_code=502, detail="Logo download failed") from exc

    entry = await _store_category_logo(
        db, brand, category, dl.content, ct, logo_url, variant=body.variant
    )
    logger.info(
        "Stored category logo for '%s' variant=%s (brand %s)",
        category, body.variant, brand_id,
    )
    return {
        "status": "ok",
        "category": category,
        "logo_url": entry["object_name"],
        "variant": body.variant,
        "attempt": body.attempt,
    }


@router.post("/{brand_id}/categories/upload-logo")
async def upload_category_logo(
    brand_id: uuid.UUID,
    category: str,
    variant: str = "light",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually upload a category's logo (overrides any web search result)."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    cat = (category or "").strip()
    if not cat:
        raise HTTPException(status_code=400, detail="category is required")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    _magic_ok = (
        (data[:4] == b"\x89PNG" and file.content_type == "image/png")
        or (data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg")
        or (
            data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
            and file.content_type == "image/webp"
        )
    )
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    entry = await _store_category_logo(
        db, brand, cat, data, file.content_type or "image/png", None, variant=variant
    )
    return {
        "status": "ok",
        "category": cat,
        "logo_url": entry["object_name"],
        "variant": variant if variant in _VENDOR_VARIANTS else "light",
    }


@router.delete("/{brand_id}/categories/logo")
async def delete_category_logo(
    brand_id: uuid.UUID,
    category: str,
    variant: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a category's stored logo. Pass ``variant`` to remove just one
    variant ("light"/"dark"); omit it to remove all of the category's logos."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    from sqlalchemy.orm.attributes import flag_modified

    guidelines = dict(brand.brand_guidelines or {})
    category_logos = dict(guidelines.get("category_logos", {}))
    variants = _vendor_variants(category_logos.get(category))
    if not variants:
        raise HTTPException(status_code=404, detail="Category logo not found")

    to_delete = (
        [variant] if variant in _VENDOR_VARIANTS else list(variants.keys())
    )
    removed_any = False
    for v in to_delete:
        entry = variants.pop(v, None)
        if entry and entry.get("object_name"):
            removed_any = True
            try:
                await minio_service.delete_file(entry["object_name"])
            except Exception:
                pass
    if not removed_any:
        raise HTTPException(status_code=404, detail="Category logo not found")

    if variants:
        category_logos[category] = variants
    else:
        category_logos.pop(category, None)
    guidelines["category_logos"] = category_logos
    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok"}


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    deleted = await brand_service.delete_brand(db, brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Brand not found")


# ── Competitor CRUD ───────────────────────────────────────────────────


@router.get("/{brand_id}/competitors", response_model=list[CompetitorResponse])
async def list_brand_competitors(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all competitors for a brand."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    stmt = (
        select(Competitor)
        .where(Competitor.brand_id == brand_id)
        .order_by(Competitor.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/{brand_id}/competitors",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_competitor(
    brand_id: uuid.UUID,
    data: CompetitorCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new competitor for a brand."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    competitor = Competitor(
        brand_id=brand_id,
        name=data.name,
        website_url=data.website_url,
        social_handles=data.social_handles or {},
        description=data.notes or data.description,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)
    return competitor


@router.put(
    "/{brand_id}/competitors/{competitor_id}", response_model=CompetitorResponse
)
async def update_competitor(
    brand_id: uuid.UUID,
    competitor_id: uuid.UUID,
    data: CompetitorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a competitor."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = select(Competitor).where(
        Competitor.id == competitor_id, Competitor.brand_id == brand_id
    )
    result = await db.execute(stmt)
    competitor = result.scalar_one_or_none()
    if competitor is None:
        raise HTTPException(status_code=404, detail="Competitor not found")

    update_data = data.model_dump(exclude_unset=True)
    # Support "notes" field from frontend mapping to "description" in model
    if "notes" in update_data:
        update_data["description"] = update_data.pop("notes")
    for key, value in update_data.items():
        setattr(competitor, key, value)

    await db.commit()
    await db.refresh(competitor)
    return competitor


@router.delete(
    "/{brand_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_competitor(
    brand_id: uuid.UUID,
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a competitor."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = select(Competitor).where(
        Competitor.id == competitor_id, Competitor.brand_id == brand_id
    )
    result = await db.execute(stmt)
    competitor = result.scalar_one_or_none()
    if competitor is None:
        raise HTTPException(status_code=404, detail="Competitor not found")

    await db.delete(competitor)
    await db.commit()
