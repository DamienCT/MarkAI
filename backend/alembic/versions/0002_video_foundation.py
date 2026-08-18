"""Video foundation + drift repair.

Idempotent by design: prod already carries some of these objects (hand-run DDL),
fresh installs get them from db/init.sql — every statement is guarded so this
revision converges any environment to the same schema.

Adds:
- events / trending_topics / channel_model_fallbacks (repo-tracked DDL at last)
- video_jobs + media_assets tables
- calendar_items status CHECK: + planned, rendering
- agent_runs status CHECK: + paused_for_review
- notifications type CHECK: + video_ready, render_failed
- engagement_metrics: watch_time_seconds, avg_view_duration_s, completion_rate
- ai_model_categories seeds: image-edit, video, tts, stt
- products (brand_id, bc_item_no) unique index (prod has it; fresh gets init.sql)

Revision ID: 0002_video_foundation
Revises: 0001_baseline
Create Date: 2026-08-18
"""

from alembic import op

revision = "0002_video_foundation"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Missing tables (no-ops where prod already created them by hand) ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id        UUID REFERENCES brands(id) ON DELETE CASCADE,
            title           VARCHAR(255) NOT NULL,
            description     TEXT,
            start_date      DATE NOT NULL,
            end_date        DATE,
            is_annual       BOOLEAN NOT NULL DEFAULT TRUE,
            category        VARCHAR(64),
            source          VARCHAR(32) NOT NULL DEFAULT 'manual',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trending_topics (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            topic           VARCHAR(255) NOT NULL,
            source          VARCHAR(50) NOT NULL DEFAULT 'google',
            source_url      TEXT,
            raw_metric      VARCHAR(50),
            velocity        VARCHAR(20) NOT NULL DEFAULT 'stable',
            relevance_score INTEGER NOT NULL DEFAULT 0,
            relevance_reason TEXT,
            llm_angle       TEXT,
            metadata        JSONB NOT NULL DEFAULT '{}',
            discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at      TIMESTAMPTZ NOT NULL,
            CONSTRAINT trending_topics_brand_topic_uniq UNIQUE (brand_id, topic)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS trending_topics_brand_idx ON trending_topics (brand_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS trending_topics_active_idx"
        " ON trending_topics (expires_at, relevance_score DESC, discovered_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_model_fallbacks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            channel         VARCHAR(50) NOT NULL,
            category        VARCHAR(50) NOT NULL,
            model_id        VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT channel_model_fallbacks_uniq UNIQUE (channel, category)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS channel_model_fallbacks_lookup_idx"
        " ON channel_model_fallbacks (category, channel) WHERE is_active = TRUE"
    )

    # ── Video tables ──
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS video_jobs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            calendar_item_id UUID REFERENCES calendar_items(id) ON DELETE CASCADE,
            content_id      UUID REFERENCES content(id) ON DELETE SET NULL,
            provider        VARCHAR(50) NOT NULL,
            model           VARCHAR(255) NOT NULL,
            mode            VARCHAR(20) NOT NULL DEFAULT 'i2v'
                            CHECK (mode IN ('i2v', 't2v', 'flf2v', 'extend')),
            prompt          TEXT NOT NULL,
            source_image_object VARCHAR(1024),
            params          JSONB NOT NULL DEFAULT '{}',
            status          VARCHAR(30) NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'submitted', 'running', 'succeeded', 'failed', 'cancelled')),
            progress        SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
            attempt         SMALLINT NOT NULL DEFAULT 0,
            provider_job_id VARCHAR(255),
            idempotency_key VARCHAR(128),
            output_object   VARCHAR(1024),
            thumbnail_object VARCHAR(1024),
            duration_s      NUMERIC(6,2),
            error_message   TEXT,
            cost_usd        NUMERIC(10,4) DEFAULT 0,
            generation_ledger JSONB NOT NULL DEFAULT '[]',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_brand_id ON video_jobs (brand_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_calendar_item ON video_jobs (calendar_item_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_video_jobs_active"
        " ON video_jobs (status, created_at) WHERE status IN ('queued', 'submitted', 'running')"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_jobs_idempotency"
        " ON video_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS media_assets (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            calendar_item_id UUID REFERENCES calendar_items(id) ON DELETE CASCADE,
            content_id      UUID REFERENCES content(id) ON DELETE CASCADE,
            kind            VARCHAR(20) NOT NULL CHECK (kind IN ('image', 'video', 'audio', 'thumbnail')),
            role            VARCHAR(50) NOT NULL,
            bucket          VARCHAR(100) NOT NULL,
            object_name     VARCHAR(1024) NOT NULL,
            mime_type       VARCHAR(100) NOT NULL,
            width           INTEGER,
            height          INTEGER,
            duration_s      NUMERIC(8,2),
            size_bytes      BIGINT,
            provider        VARCHAR(50),
            model           VARCHAR(255),
            prompt          TEXT,
            cost_usd        NUMERIC(10,4),
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_brand_id ON media_assets (brand_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_calendar_item ON media_assets (calendar_item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_content ON media_assets (content_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_media_assets_kind_role ON media_assets (kind, role)")

    # ── CHECK constraint repairs/extensions ──
    op.execute("ALTER TABLE calendar_items DROP CONSTRAINT IF EXISTS calendar_items_status_check")
    op.execute(
        """
        ALTER TABLE calendar_items ADD CONSTRAINT calendar_items_status_check
        CHECK (status IN ('planned', 'queued', 'working', 'rendering', 'in_review', 'reworking',
                          'approved', 'scheduled', 'publishing', 'published', 'failed'))
        """
    )
    op.execute("ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_status_check")
    op.execute(
        """
        ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_status_check
        CHECK (status IN ('pending', 'running', 'paused_for_review', 'completed', 'failed', 'cancelled'))
        """
    )
    op.execute("ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_notification_type_check")
    op.execute(
        """
        ALTER TABLE notifications ADD CONSTRAINT notifications_notification_type_check
        CHECK (notification_type IN ('info', 'success', 'warning', 'error',
                                     'approval_request', 'approval_decision',
                                     'content_ready', 'publish_success',
                                     'publish_failure', 'system',
                                     'context_ready', 'context_all_ready',
                                     'linkedin_token_expiry', 'runway_alert',
                                     'stuck_in_review', 'video_ready', 'render_failed'))
        """
    )

    # ── engagement_metrics video columns ──
    op.execute("ALTER TABLE engagement_metrics ADD COLUMN IF NOT EXISTS watch_time_seconds INTEGER")
    op.execute("ALTER TABLE engagement_metrics ADD COLUMN IF NOT EXISTS avg_view_duration_s NUMERIC(8,2)")
    op.execute("ALTER TABLE engagement_metrics ADD COLUMN IF NOT EXISTS completion_rate NUMERIC(5,4)")

    # ── Category seeds ──
    op.execute(
        """
        INSERT INTO ai_model_categories (slug, display_name, description) VALUES
            ('image-edit', 'Image Editing',   'Models for editing images (product swap, inpainting)'),
            ('video',      'Video Generation','Models for generating short-form video (local or cloud)'),
            ('tts',        'Text to Speech',  'Voice synthesis models for voiceovers'),
            ('stt',        'Speech to Text',  'Transcription models for subtitles and captions')
        ON CONFLICT (slug) DO NOTHING
        """
    )

    # ── Product uniqueness (prod already has it; fresh installs via init.sql) ──
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_brand_bc_item"
        " ON products (brand_id, bc_item_no) WHERE bc_item_no IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS media_assets")
    op.execute("DROP TABLE IF EXISTS video_jobs")
    op.execute("ALTER TABLE engagement_metrics DROP COLUMN IF EXISTS completion_rate")
    op.execute("ALTER TABLE engagement_metrics DROP COLUMN IF EXISTS avg_view_duration_s")
    op.execute("ALTER TABLE engagement_metrics DROP COLUMN IF EXISTS watch_time_seconds")
    # CHECK constraints, seed rows, and the drift-repair tables are left in place:
    # reverting them would break data already written under the wider definitions.
