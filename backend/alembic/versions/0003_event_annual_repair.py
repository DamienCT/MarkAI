"""Repair legacy movable-holiday events stored as annual.

Rows detected before coerce_is_annual existed (or before it covered
weekday-relative observances) were stored with is_annual=TRUE, and the dedup
key in detect_events_via_llm skips re-detected duplicates, so those rows never
pass through the coercion again — annual projection keeps emitting wrong dates
for them every year. One-off, idempotent data fix.

The pattern mirrors _MOVABLE_HOLIDAY_RE + _WEEKDAY_RELATIVE_RE in
app/services/event_service.py as of this revision (frozen here on purpose —
migrations must not drift with application code). Postgres \\m / \\M are the
word-boundary equivalents of Python's \\b, so 'Eidsvoll Day' stays untouched
while 'Eid ul-Fitr' is repaired.

Revision ID: 0003_event_annual_repair
Revises: 0002_video_foundation
Create Date: 2026-08-18
"""

from alembic import op

revision = "0003_event_annual_repair"
down_revision = "0002_video_foundation"
branch_labels = None
depends_on = None

_MOVABLE_TITLE_SQL_RE = (
    r"\m(diwali|divali|deepavali"
    r"|eid"
    r"|ganesh"
    r"|chinese\s+new\s+year|spring\s+festival"
    r"|thaipoosam|cavadee"
    r"|shivaratri|shivaratree"
    r"|ougadi|ugadi"
    r"|easter"
    r"|ash\s+wednesday"
    r"|black\s+friday"
    r"|cyber\s+monday"
    r"|mother'?s\s+day"
    r"|father'?s\s+day"
    r"|thanksgiving)\M"
)


def upgrade() -> None:
    op.execute(
        "UPDATE events SET is_annual = FALSE, updated_at = NOW() "
        "WHERE is_annual = TRUE AND title ~* '"
        + _MOVABLE_TITLE_SQL_RE.replace("'", "''")
        + "'"
    )


def downgrade() -> None:
    # Data repair — not reversible: the original (wrong) is_annual flags are
    # not worth restoring, and re-annualizing movable holidays would reintroduce
    # the wrong-date projection this migration exists to stop.
    pass
