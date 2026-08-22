"""HITL durable resume + worker leases — 2026-08-22 round.

Idempotent convergence revision (same style as 0005): prod may already carry
pieces of this from hand-run DDL, fresh installs get everything from
db/init.sql — every statement is guarded so any environment converges.

Adds:
- agent_runs.claimed_by TEXT — WORKER_ID of the worker holding the run's
  lease (default "hostname:pid", env-overridable). The drain and the resume
  CAS both filter on it, so one worker can never fail or resume another
  worker's rows (AG-11/BE-34 lease model).
- agent_runs.heartbeat_at TIMESTAMPTZ — refreshed ~every 30s for every
  in-flight run; the stale_run_reaper fails runs on heartbeat expiry
  ("lease expired") instead of the old age-only guess.
- idx_agent_runs_heartbeat (status, heartbeat_at) — the reaper's scan path.

Revision ID: 0006_hitl_leases
Revises: 0005_audit_containment
Create Date: 2026-08-22
"""

from alembic import op

revision = "0006_hitl_leases"
down_revision = "0005_audit_containment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Worker lease columns on agent_runs ──
    op.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS claimed_by TEXT")
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ"
    )

    # ── Reaper scan: running rows with an expired heartbeat ──
    # Definition matches db/init.sql verbatim (fresh installs get it there).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_heartbeat"
        " ON agent_runs (status, heartbeat_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_runs_heartbeat")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS heartbeat_at")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS claimed_by")
