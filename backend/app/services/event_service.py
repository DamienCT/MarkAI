import json
import logging
import uuid
from datetime import date, timedelta
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate

logger = logging.getLogger(__name__)


async def list_events(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    include_global: bool = True,
    category: str | None = None,
    upcoming_only: bool = False,
) -> Sequence[Event]:
    """List events.

    - brand_id=None + include_global=True → all events (global + every brand).
    - brand_id=<uuid> + include_global=True → that brand's events + global.
    - brand_id=<uuid> + include_global=False → only that brand.
    - brand_id=None + include_global=False → only global events.

    ``upcoming_only`` keeps rows whose occurrence is today or later. Annual
    events are treated as always upcoming (their recurrence is projected at
    prompt-build time, not at list time).
    """
    stmt = select(Event)

    if brand_id is not None and include_global:
        stmt = stmt.where(or_(Event.brand_id == brand_id, Event.brand_id.is_(None)))
    elif brand_id is not None:
        stmt = stmt.where(Event.brand_id == brand_id)
    elif not include_global:
        stmt = stmt.where(Event.brand_id.is_(None))

    if category:
        stmt = stmt.where(Event.category == category)

    if upcoming_only:
        today = date.today()
        stmt = stmt.where(
            or_(
                Event.is_annual.is_(True),
                Event.start_date >= today,
                and_(Event.end_date.isnot(None), Event.end_date >= today),
            )
        )

    stmt = stmt.order_by(Event.start_date.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_event(db: AsyncSession, event_id: uuid.UUID) -> Event | None:
    result = await db.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


async def create_event(db: AsyncSession, data: EventCreate) -> Event:
    event = Event(**data.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def update_event(
    db: AsyncSession, event_id: uuid.UUID, data: EventUpdate
) -> Event | None:
    event = await get_event(db, event_id)
    if event is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(event, key, value)
    await db.commit()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, event_id: uuid.UUID) -> bool:
    event = await get_event(db, event_id)
    if event is None:
        return False
    await db.delete(event)
    await db.commit()
    return True


def _project_annual(start: date, today: date) -> date:
    """Shift an annual event's month/day to the current or next year."""
    try:
        this_year = start.replace(year=today.year)
    except ValueError:
        # Feb 29 on a non-leap year — fall back to Feb 28
        this_year = start.replace(year=today.year, day=28)
    if this_year >= today:
        return this_year
    try:
        return start.replace(year=today.year + 1)
    except ValueError:
        return start.replace(year=today.year + 1, day=28)


async def get_events_for_context(
    db: AsyncSession,
    brand_id: uuid.UUID | None,
    *,
    months_ahead: int = 12,
) -> list[dict]:
    """Return events applicable to the next ``months_ahead`` for research.

    Unions global (brand_id IS NULL) + brand-specific events. Annual events
    are projected to their current or next occurrence so the list is always
    forward-looking from today and downstream LLM prompts see concrete dates.
    Results are returned as plain dicts (LLM-ready, not ORM objects).
    """
    rows = await list_events(db, brand_id=brand_id, include_global=True)
    today = date.today()
    horizon = today + timedelta(days=months_ahead * 31)  # loose upper bound

    out: list[dict] = []
    for ev in rows:
        occ_start = _project_annual(ev.start_date, today) if ev.is_annual else ev.start_date
        if ev.end_date and ev.start_date:
            duration = (ev.end_date - ev.start_date).days
            occ_end = occ_start + timedelta(days=duration)
        else:
            occ_end = occ_start

        # Skip events outside the window (non-annual past events, or occurrences
        # that land beyond the horizon)
        if occ_end < today or occ_start > horizon:
            continue

        out.append(
            {
                "title": ev.title,
                "description": ev.description or "",
                "start": occ_start.isoformat(),
                "end": occ_end.isoformat() if occ_end != occ_start else None,
                "category": ev.category,
                "annual": ev.is_annual,
                "scope": "global" if ev.brand_id is None else "brand",
            }
        )

    out.sort(key=lambda e: e["start"])
    return out


async def detect_events_via_llm(
    db: AsyncSession,
    brand: dict | None,
    *,
    brand_id: uuid.UUID | None,
    horizon_months: int = 12,
) -> list[Event]:
    """Ask the LLM for relevant significant dates and persist them.

    ``brand`` may be None for global detection; the LLM then suggests broadly
    relevant international and Mauritius-based dates. De-dupes against
    existing rows on (title, month-day, brand_id) so re-running doesn't
    duplicate entries.
    """
    from app.api.v1.intelligence import _call_llm

    brand_context_parts = []
    if brand:
        brand_context_parts.append(f"Brand: {brand.get('name', 'Unknown')}")
        if brand.get("description"):
            brand_context_parts.append(f"Description: {brand['description']}")
        audience = brand.get("target_audience") or {}
        if audience:
            brand_context_parts.append(f"Target audience: {json.dumps(audience)[:500]}")
        guidelines = brand.get("brand_guidelines") or {}
        industry = guidelines.get("industry") if isinstance(guidelines, dict) else None
        if industry:
            brand_context_parts.append(f"Industry: {industry}")
    else:
        brand_context_parts.append(
            "Scope: global list (applies to all brands — prefer internationally "
            "recognised awareness days plus Mauritius public holidays)."
        )

    brand_context = "\n".join(brand_context_parts) or "No brand context provided."

    system = (
        "You are a marketing calendar expert. Produce a list of significant "
        "dates and observances for the next " + str(horizon_months) + " months "
        "that would be relevant for a brand's content marketing. Include: "
        "Mauritius public holidays, internationally recognised awareness days "
        "(health, cause-related, cultural), industry-specific dates if an "
        "industry is given, and major commercial moments (Black Friday, "
        "Mother's Day, etc.). Return STRICT JSON with a single key 'events' "
        "whose value is an array. Each event must have: title (string), "
        "description (one short sentence, max 200 chars), start_date "
        "(YYYY-MM-DD, use the next occurrence from today), end_date (YYYY-MM-DD "
        "or null for single-day), is_annual (boolean — true for recurring "
        "yearly observances), category (one of: holiday, awareness, industry, "
        "local, custom)."
    )
    user = f"Context:\n{brand_context}\n\nReturn 15-30 events."

    raw = await _call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
        json_mode=True,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("detect_events_via_llm: LLM did not return valid JSON")
        return []

    events_raw = parsed.get("events") if isinstance(parsed, dict) else None
    if not isinstance(events_raw, list):
        return []

    # Load existing events for dedup on (lower(title), month-day, brand_id)
    existing = await list_events(db, brand_id=brand_id, include_global=(brand_id is None))
    seen: set[tuple[str, str, uuid.UUID | None]] = set()
    for e in existing:
        seen.add((e.title.strip().lower(), e.start_date.strftime("%m-%d"), e.brand_id))

    created: list[Event] = []
    for item in events_raw:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        start_raw = item.get("start_date")
        if not title or not start_raw:
            continue
        try:
            start = date.fromisoformat(str(start_raw))
        except (ValueError, TypeError):
            continue

        key = (title.lower(), start.strftime("%m-%d"), brand_id)
        if key in seen:
            continue
        seen.add(key)

        end_raw = item.get("end_date")
        end: date | None = None
        if end_raw:
            try:
                end = date.fromisoformat(str(end_raw))
            except (ValueError, TypeError):
                end = None

        category = item.get("category")
        if category and not isinstance(category, str):
            category = None

        event = Event(
            brand_id=brand_id,
            title=title[:255],
            description=(item.get("description") or "")[:500] or None,
            start_date=start,
            end_date=end,
            is_annual=bool(item.get("is_annual", True)),
            category=category,
            source="ai_detected",
        )
        db.add(event)
        created.append(event)

    if created:
        await db.commit()
        for ev in created:
            await db.refresh(ev)

    return created


async def latest_updated_at(
    db: AsyncSession, brand_id: uuid.UUID | None
) -> str | None:
    """Return max(updated_at) across global + brand events as ISO string."""
    from sqlalchemy import func as sqlfunc

    stmt = select(sqlfunc.max(Event.updated_at))
    if brand_id is not None:
        stmt = stmt.where(or_(Event.brand_id == brand_id, Event.brand_id.is_(None)))
    result = await db.execute(stmt)
    value = result.scalar_one_or_none()
    return value.isoformat() if value else None
