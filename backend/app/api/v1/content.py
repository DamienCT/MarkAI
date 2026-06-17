import logging
import os as _os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.calendar_item import CalendarItem
from app.models.product import Product
from app.schemas.content import ContentCreate, ContentResponse, ContentUpdate
from app.services import brand_service, content_service, minio_service
from app.services.content_service import InvalidStatusTransition
from app.utils.sanitize import sanitize_for_prompt as _sanitize

logger = logging.getLogger(__name__)

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


@router.get("/", response_model=list[ContentResponse])
async def list_content(
    brand_id: uuid.UUID | None = None,
    is_current: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    return await content_service.list_content(
        db, brand_id=brand_id, is_current=is_current, skip=skip, limit=limit
    )


@router.get("/by-calendar-item/{calendar_item_id}", response_model=ContentResponse)
async def get_content_by_calendar_item(
    calendar_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current content record for a calendar item."""
    item = await content_service.get_content_by_calendar_item(db, calendar_item_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail="Content not found for this calendar item"
        )
    return item


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await content_service.get_content(db, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item


@router.post("/", response_model=ContentResponse, status_code=status.HTTP_201_CREATED)
async def create_content(
    data: ContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await content_service.create_content(db, data)


@router.put("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: uuid.UUID,
    data: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        item = await content_service.update_content(db, content_id, data)
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=422, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item


class ImageRegenerateRequest(BaseModel):
    prompt: str | None = None
    format: str | None = None  # "lifestyle" (default) | "ad"


@router.post("/{content_id}/regenerate-image")
async def regenerate_image(
    content_id: uuid.UUID,
    body: ImageRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate the image for an existing content piece without recreating the text."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content = await content_service.get_content(db, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Publish a NATS message to trigger image regeneration
    from app.services import nats_service

    await nats_service.publish(
        "content.regenerate-image",
        {
            "content_id": str(content_id),
            "brand_id": str(content.brand_id),
            "calendar_item_id": str(content.calendar_item_id),
            "custom_prompt": (body.prompt if body else None),
            "image_format": ((body.format if body else None) or "lifestyle"),
        },
    )

    return {"status": "queued", "message": "Image regeneration started"}


class LogoRebrandRequest(BaseModel):
    """Manual logo/overlay placement from the visual editor.

    Coordinates are normalized 0..1 CENTER points; scales are width-relative
    (logo) / font multiplier (text). ``text_xy`` may be null to keep the
    text at its current/anchor position.
    """

    logo_xy: list[float]
    logo_scale: float | None = None
    text_xy: list[float] | None = None
    text_scale: float | None = 1.0
    logo_variant: str | None = None
    text_style: str | None = None  # "glass" (default) | "solid" | "headline"
    font_family: str | None = None  # headline font (e.g. "Montserrat")
    headline_colors: dict[str, str] | None = None  # word index -> "#RRGGBB"
    text_stretch_x: float | None = None  # headline horizontal stretch (1.0 = none)
    text_stretch_y: float | None = None  # headline vertical stretch (1.0 = none)


# Manual logo/overlay editing is only allowed while the post is in review.
_REBRAND_ALLOWED_STATUSES = frozenset({"in_review", "reworking"})


@router.post("/{content_id}/rebrand-logo")
async def rebrand_logo(
    content_id: uuid.UUID,
    body: LogoRebrandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-render the branded image with manually-placed logo + text overlay.

    Publishes a NATS message the agents worker handles by re-compositing from
    the clean base image (no re-generation), keeping the underlying photo.
    """
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content = await content_service.get_content(db, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    cal_result = await db.execute(
        select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
    )
    cal_item = cal_result.scalar_one_or_none()
    if cal_item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    if cal_item.status not in _REBRAND_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Logo editing is only allowed for in-review content (got '{cal_item.status}')",
        )

    if len(body.logo_xy) != 2:
        raise HTTPException(status_code=400, detail="logo_xy must be [x, y]")
    if body.text_xy is not None and len(body.text_xy) != 2:
        raise HTTPException(status_code=400, detail="text_xy must be [x, y] or null")

    # Flip to 'working' synchronously BEFORE returning so the client's status
    # poll can't race past the (fast) re-render and reload a stale image. The
    # worker restores `prior_status` when it finishes.
    prior_status = cal_item.status
    cal_item.status = "working"
    await db.commit()

    from app.services import nats_service

    await nats_service.publish(
        "content.rebrand-logo",
        {
            "content_id": str(content_id),
            "brand_id": str(content.brand_id),
            "calendar_item_id": str(content.calendar_item_id),
            "logo_xy": body.logo_xy,
            "logo_scale": body.logo_scale,
            "text_xy": body.text_xy,
            "text_scale": body.text_scale,
            "logo_variant": body.logo_variant,
            "text_style": body.text_style,
            "font_family": body.font_family,
            "headline_colors": body.headline_colors,
            "text_stretch_x": body.text_stretch_x,
            "text_stretch_y": body.text_stretch_y,
            "prior_status": prior_status,
        },
    )

    return {"status": "queued", "message": "Logo re-render started"}


class CaptionRegenerateRequest(BaseModel):
    prompt: str | None = None


# Per-channel default word caps used when no per-channel override is set.
# Same defaults the content workflow uses for caption length.
_DEFAULT_MAX_WORDS_BY_CHANNEL = {
    "instagram": 60,
    "facebook": 90,
    "linkedin": 120,
    "tiktok": 30,
    "x": 35,
    "website_blog": 800,
    "teams": 80,
}


@router.post("/{content_id}/regenerate-caption", response_model=ContentResponse)
@_limiter.limit("20/minute")
async def regenerate_caption(
    request: Request,
    content_id: uuid.UUID,
    body: CaptionRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate just the caption for an existing content piece.

    Synchronous — one LLM call, no NATS round-trip. Image regeneration uses
    NATS because it takes 30 to 180s; caption is one to three seconds so the
    polling/queue overhead would just hurt UX. Uses the brand voice profile
    plus any per-channel Custom Channel Rules so the regenerated caption
    respects the same constraints as a fresh generation.
    """
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content_obj = await content_service.get_content(db, content_id)
    if content_obj is None:
        raise HTTPException(status_code=404, detail="Content not found")

    brand = await brand_service.get_brand(db, content_obj.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # The channel lives on the calendar item, not on content.
    cal_item = await db.get(CalendarItem, content_obj.calendar_item_id)
    channel = ((cal_item.channel if cal_item else "") or "").lower()

    # Load the product actually linked to this item (product_ids). This is the
    # SAME product shown in the post image, so the caption must feature it — even
    # if the brief's prose names a different product (a known planning bug where
    # the brief mentions a product that doesn't match the linked product_ids).
    linked_product = None
    _pids = (getattr(cal_item, "product_ids", None) or []) if cal_item else []
    if _pids:
        try:
            linked_product = await db.get(Product, uuid.UUID(str(_pids[0])))
        except (ValueError, TypeError):
            linked_product = None

    guidelines = brand.brand_guidelines or {}
    channel_rules = (
        ((guidelines.get("channels") or {}).get(channel) or {}).get("caption") or {}
    )

    ta_desc = (
        (brand.target_audience or {}).get("description", "Not set")
        if isinstance(brand.target_audience, dict)
        else "Not set"
    )

    title = (content_obj.headline or "").strip()
    if cal_item is not None:
        brief = cal_item.content_brief or cal_item.description or cal_item.title or ""
        pillar = cal_item.pillar or ""
        audience = cal_item.target_audience or ""
    else:
        brief = ""
        pillar = ""
        audience = ""

    tone_override = channel_rules.get("tone_override") or brand.tone_of_voice or ""
    emoji_override = channel_rules.get("emoji_override") or guidelines.get(
        "emoji_usage", "moderate"
    )
    max_words = int(
        channel_rules.get("max_words")
        or _DEFAULT_MAX_WORDS_BY_CHANNEL.get(channel, 90)
    )
    hook_format = channel_rules.get("hook_format") or ""
    structure_template = channel_rules.get("structure_template") or ""
    extra_brief = channel_rules.get("caption_brief") or ""
    must_name_product = bool(channel_rules.get("must_name_product"))

    custom_request = ((body.prompt if body else None) or "").strip()
    previous_caption = (content_obj.caption or "").strip()

    system_parts: list[str] = [
        f"You write social captions for {_sanitize(brand.name or '')} on "
        f"{_sanitize(channel or 'social')}.",
        f"Brand description: {_sanitize(brand.description or 'Not set')}",
        f"Tone of voice: {_sanitize(tone_override or 'Not set')}",
        f"Voice style: {_sanitize(guidelines.get('voice_style', 'Not set'))}",
        f"Target audience: {_sanitize(ta_desc)}",
        f"Dos: {_sanitize(', '.join(guidelines.get('dos', [])) or 'Not set')}",
        f"Donts: {_sanitize(', '.join(guidelines.get('donts', [])) or 'Not set')}",
        f"Emoji usage: {_sanitize(str(emoji_override))}",
    ]
    if hook_format:
        system_parts.append(f"Hook format: {_sanitize(hook_format)}")
    if structure_template:
        system_parts.append(f"Structure template: {_sanitize(structure_template)}")
    if extra_brief:
        system_parts.append(f"Extra brief for this channel: {_sanitize(extra_brief)}")

    system_parts.append("")
    system_parts.append("ABSOLUTE RULES:")
    system_parts.append(f"- HARD limit: stay strictly under {max_words} words.")
    system_parts.append(
        "- NEVER include hashtags (#anything) inside the caption body. "
        "Hashtags live in a separate field appended later."
    )
    system_parts.append(
        "- Open with a single hook line. Separate distinct sections with a "
        "blank line."
    )
    system_parts.append(
        "- End with a short CTA line (e.g. 'Shop now', 'Try it today'). "
        "NEVER include URLs or links of any kind in the caption."
    )
    system_parts.append(
        "- Avoid AI cliches: elevate, unlock, discover, journey, dive, "
        "transform, empower, seamless, robust, leverage, embark, foster, "
        "harness, holistic."
    )
    system_parts.append("- No em-dashes between clauses.")
    if must_name_product:
        system_parts.append("- Mention the product by name.")
    if linked_product is not None and (linked_product.name or "").strip():
        system_parts.append(
            f'- PRODUCT TO FEATURE (authoritative): this post is about '
            f'"{_sanitize(linked_product.name)}" — the exact product shown in the '
            f"post image. If the brief names a different product, that name is "
            f"wrong: ignore it and write about this product. Any product named in "
            f"the caption MUST be exactly this one."
        )
    system_parts.append(
        "Return ONLY the caption body. No markdown headers, no quotes, no "
        "explanations."
    )

    user_parts: list[str] = []
    user_parts.append(f"Post title: {_sanitize(title or '(none)')}")
    user_parts.append(f"Brief: {_sanitize(brief or '(none)')}")
    if linked_product is not None and (linked_product.name or "").strip():
        user_parts.append("")
        user_parts.append(
            "PRODUCT TO FEATURE (authoritative — overrides any product named in "
            f"the brief): {_sanitize(linked_product.name)}"
        )
        if linked_product.description:
            user_parts.append(
                f"Product description: {_sanitize(linked_product.description)}"
            )
        if linked_product.category:
            user_parts.append(
                f"Product category: {_sanitize(linked_product.category)}"
            )
    if pillar:
        user_parts.append(f"Pillar: {_sanitize(pillar)}")
    if audience:
        user_parts.append(f"Audience: {_sanitize(audience)}")
    if previous_caption:
        user_parts.append("")
        user_parts.append("Previous caption (for reference — do not copy):")
        user_parts.append(_sanitize(previous_caption[:600]))
    if custom_request:
        user_parts.append("")
        user_parts.append(
            f"Additional guidance from editor: {_sanitize(custom_request)}"
        )
    user_parts.append("")
    user_parts.append(
        "Write a fresh caption that follows the rules above. Use a different "
        "wording and angle from any previous version."
    )

    # Import here to avoid a circular import at module load time.
    from app.api.v1.intelligence import _call_llm

    try:
        raw = await _call_llm(
            messages=[
                {"role": "system", "content": "\n".join(system_parts)},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            temperature=0.8,
        )
    except Exception as exc:
        logger.error("Caption regeneration LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Caption regeneration failed")

    new_caption = (raw or "").strip().strip('"').strip("'").strip()
    if not new_caption:
        raise HTTPException(status_code=502, detail="LLM returned empty caption")

    updated = await content_service.update_content(
        db, content_id, ContentUpdate(caption=new_caption)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return updated


# Statuses where the image is effectively locked — the content either went out
# the door or errored out terminally. Uploading over it would rewrite history.
_IMAGE_LOCKED_STATUSES = frozenset({"published", "failed"})


@router.post("/{content_id}/upload-image", response_model=ContentResponse)
@_limiter.limit("20/minute")
async def upload_content_image(
    request: Request,
    content_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the AI-generated image with a user-uploaded one.

    Blocked once the linked calendar item is published or failed — those are
    terminal states where the image is treated as the canonical delivered asset.
    """
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content = await content_service.get_content(db, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Status lives on CalendarItem; block edits on terminal statuses.
    cal_result = await db.execute(
        select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
    )
    cal_item = cal_result.scalar_one_or_none()
    if cal_item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    if cal_item.status in _IMAGE_LOCKED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit image for content in '{cal_item.status}' state",
        )

    # Validate content type — images only (SVG excluded to prevent stored XSS)
    _allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if not file.content_type or file.content_type not in _allowed_types:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    file_data = await file.read()

    # Validate file size — max 5 MB
    if len(file_data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate magic bytes match declared content type
    _magic_ok = False
    if file_data[:4] == b"\x89PNG" and file.content_type == "image/png":
        _magic_ok = True
    elif file_data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg":
        _magic_ok = True
    elif (
        file_data[:4] == b"RIFF"
        and file_data[8:12] == b"WEBP"
        and file.content_type == "image/webp"
    ):
        _magic_ok = True
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    safe_filename = f"{uuid.uuid4().hex}{_os.path.splitext(file.filename or '.jpg')[1]}"
    object_name = f"contents/{content_id}/{safe_filename}"
    content_type = file.content_type or "image/jpeg"

    await minio_service.upload_file(object_name, file_data, content_type)

    # Render priority is branded_image → raw_image → generated_image_url, so
    # writing to branded_image guarantees the upload wins regardless of what
    # prior AI runs left in the other slots.
    metadata = dict(content.generation_metadata) if content.generation_metadata else {}
    metadata["branded_image"] = object_name
    metadata["user_uploaded_image"] = object_name
    content.generation_metadata = metadata
    flag_modified(content, "generation_metadata")
    await db.commit()
    await db.refresh(content)
    return content


@router.post("/{content_id}/transition", response_model=ContentResponse)
async def transition_content_status(
    content_id: uuid.UUID,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        item = await content_service.transition_status(db, content_id, new_status)
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=422, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item
