"""Per-brand AI model profiles (image + video adapters).

Each brand/company can carry its own fine-tuned adapter per media kind,
served from the GPU forge (the adapter FILE lives on the forge box under
ComfyUI models/loras — this table stores only its name and how to use it).
One row per (brand, kind) at most in status 'ready': the render pipelines
look up the ready profile for the brand and pass adapter_name/strength
through to the forge as lora_name/lora_strength.

status lifecycle: training -> ready | failed; disabled parks an adapter
without deleting its history. LTX Community License note: video adapter
files must NEVER leave our infrastructure (non-transferable Derivatives) —
hence a name reference, not bytes, and no client-facing surface.

Revision ID: 0004_brand_model_profiles
Revises: 0003_event_annual_repair
Create Date: 2026-08-21
"""

from alembic import op

revision = "0004_brand_model_profiles"
down_revision = "0003_event_annual_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS brand_model_profiles (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            kind            TEXT NOT NULL CHECK (kind IN ('image', 'video')),
            base_model      TEXT NOT NULL,
            adapter_name    TEXT NOT NULL,
            trigger_token   TEXT,
            strength        DOUBLE PRECISION NOT NULL DEFAULT 1.0
                            CHECK (strength >= 0.0 AND strength <= 2.0),
            status          TEXT NOT NULL DEFAULT 'training'
                            CHECK (status IN ('training', 'ready', 'failed', 'disabled')),
            notes           TEXT,
            trained_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_brand_model_profiles_brand "
        "ON brand_model_profiles (brand_id, kind)"
    )
    # At most one READY adapter per brand+kind — the render-time lookup must
    # never have to pick between two live adapters.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_model_profiles_ready "
        "ON brand_model_profiles (brand_id, kind) WHERE status = 'ready'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS brand_model_profiles")
