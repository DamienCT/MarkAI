"""Audit containment — 2026-08-21 remediation round.

Idempotent convergence revision (same style as 0002): prod may already carry
pieces of this from hand-run DDL, fresh installs get everything from
db/init.sql — every statement is guarded so any environment converges.

Adds:
- products.metadata JSONB (product-intel match/image-sourcing results had no
  column to land in and were silently discarded — N-06 persistence contract)
- system_flags table (operational toggles; key 'publishing_enabled' backs the
  publishing kill switch)
- webhook_events table (inbound callback replay protection keyed on
  X-Webhook-Event-Id)
- idx_engagement_metrics_content_fetched — existed only in init.sql, added
  two days after the 0001 baseline, so prod could never receive it (N-17)
- adaptations status CHECK widened with 'applied', 'rejected' — the learning
  loop's apply/reject writes violated the old CHECK (N-10)

Revision ID: 0005_audit_containment
Revises: 0004_brand_model_profiles
Create Date: 2026-08-21
"""

from alembic import op

revision = "0005_audit_containment"
down_revision = "0004_brand_model_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── products.metadata (N-06) ──
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'"
    )

    # ── System flags (publishing kill switch et al.) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_flags (
            key             TEXT PRIMARY KEY,
            value           JSONB NOT NULL DEFAULT '{}',
            updated_by      TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # init.sql's catch-all updated_at trigger loop ran long before this table
    # existed on prod, so attach the trigger here. Guarded on the function so
    # an environment that somehow lacks update_updated_at_column() no-ops
    # instead of failing mid-migration.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
                DROP TRIGGER IF EXISTS trigger_updated_at ON system_flags;
                CREATE TRIGGER trigger_updated_at BEFORE UPDATE ON system_flags
                    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
            END IF;
        END
        $$
        """
    )

    # ── Webhook events (replay protection) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            event_id        TEXT PRIMARY KEY,
            received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # ── Latest-snapshot engagement lookups (N-17) ──
    # Definition copied verbatim from db/init.sql (idx added there after the
    # 0001 baseline; this is its first appearance in the migration chain).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_engagement_metrics_content_fetched"
        " ON engagement_metrics (content_id, fetched_at DESC)"
    )

    # ── adaptations status CHECK: + applied, rejected (N-10) ──
    # Guarded swap: only rewrites the constraint when it doesn't yet allow
    # 'rejected' (probe on 'rejected', not 'applied' — 'auto_applied' would
    # substring-match the latter). Hand-patched or re-run environments no-op.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'adaptations'::regclass
                  AND conname = 'adaptations_status_check'
                  AND pg_get_constraintdef(oid) LIKE '%rejected%'
            ) THEN
                ALTER TABLE adaptations DROP CONSTRAINT IF EXISTS adaptations_status_check;
                ALTER TABLE adaptations ADD CONSTRAINT adaptations_status_check
                    CHECK (status IN ('queued', 'working', 'in_review', 'reworking',
                                      'approved', 'scheduled', 'published', 'failed',
                                      'proposed', 'auto_applied', 'applied', 'rejected'));
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_events")
    op.execute("DROP TABLE IF EXISTS system_flags")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS metadata")
    op.execute("DROP INDEX IF EXISTS idx_engagement_metrics_content_fetched")
    # The widened adaptations CHECK stays in place: narrowing it back would
    # break rows already written as applied/rejected (same policy as 0002's
    # downgrade note on constraint widenings).
