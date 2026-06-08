"""Audit-trail recording.

Writes one row to ``audit_log`` per security-relevant user action. The action
taxonomy and resource types mirror the filter dropdowns in the Audit Log UI:
  actions:   create | update | delete | approve | reject | publish
  resources: brand | content | approval | user | prompt | system

``record_audit`` is fire-and-forget: it uses its OWN short-lived session (so it
never touches the caller's transaction or the ORM object the endpoint returns),
and it swallows every error — auditing must never break the underlying action.
"""

import logging
import uuid as _uuid
from typing import Any

logger = logging.getLogger(__name__)


async def record_audit(
    *,
    action: str,
    entity_type: str,
    user_id: _uuid.UUID | None = None,
    entity_id: _uuid.UUID | str | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    request: Any | None = None,
) -> None:
    """Record an audit event. Best-effort — never raises."""
    try:
        from app.models.base import async_session_factory
        from app.auth.models import AuditLog

        # entity_id may arrive as a string; coerce to UUID when possible.
        eid: _uuid.UUID | None = None
        if isinstance(entity_id, _uuid.UUID):
            eid = entity_id
        elif isinstance(entity_id, str) and entity_id:
            try:
                eid = _uuid.UUID(entity_id)
            except ValueError:
                eid = None

        ip = None
        ua = None
        if request is not None:
            client = getattr(request, "client", None)
            ip = getattr(client, "host", None)
            try:
                ua = request.headers.get("user-agent")
            except Exception:
                ua = None

        async with async_session_factory() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=eid,
                    old_values=old_values,
                    new_values=new_values,
                    ip_address=ip,
                    user_agent=ua,
                )
            )
            await session.commit()
    except Exception as exc:  # never break the caller's action
        logger.warning(
            "audit record failed (action=%s entity=%s): %s",
            action, entity_type, exc,
        )
