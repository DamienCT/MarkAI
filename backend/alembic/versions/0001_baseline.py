"""Baseline — schema as shipped by db/init.sql (and hand-drifted prod as of 2026-08-18).

This revision intentionally creates nothing. Fresh installs get the full schema
from db/init.sql on first postgres boot; existing databases (prod) already carry
it. The entrypoint stamps this revision when the alembic_version table is absent,
so every environment shares a common migration ancestor from here on.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-18
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
