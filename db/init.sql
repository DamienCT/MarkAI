-- MARKAI Database Schema
-- PostgreSQL 16

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users ───────────────────────────────────────────────────────
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entra_object_id VARCHAR(255) UNIQUE NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    display_name    VARCHAR(255) NOT NULL,
    avatar_url      TEXT,
    role            VARCHAR(50) NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('admin', 'manager', 'editor', 'viewer')),
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- idx_users_email and idx_users_entra_object_id removed: UNIQUE constraints already create indexes
CREATE INDEX idx_users_role ON users (role);

-- ── Brands ──────────────────────────────────────────────────────
CREATE TABLE brands (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT,
    website_url     TEXT,
    logo_url        TEXT,
    brand_guidelines JSONB DEFAULT '{}',
    tone_of_voice   TEXT,
    target_audience JSONB DEFAULT '{}',
    color_palette   JSONB DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    status          VARCHAR(50) NOT NULL DEFAULT 'onboarding'
                    CHECK (status IN ('onboarding', 'activating', 'active', 'inactive')),
    onboarding_completed_at TIMESTAMPTZ,
    activation_started_at   TIMESTAMPTZ,
    is_bc_linked    BOOLEAN NOT NULL DEFAULT FALSE,
    bc_company      VARCHAR(255),
    bc_locations    JSONB DEFAULT '[]',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_brands_created_by ON brands (created_by);
CREATE INDEX idx_brands_bc_company ON brands (bc_company);
CREATE INDEX idx_brands_status ON brands (status);

-- ── Products ────────────────────────────────────────────────────
CREATE TABLE products (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id            UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    bc_item_no          VARCHAR(50),
    bc_item_category    VARCHAR(255),
    name                VARCHAR(500) NOT NULL,
    description         TEXT,
    short_description   TEXT,
    sku                 VARCHAR(255),
    barcode             VARCHAR(255),
    unit_price          NUMERIC(12,2),
    currency            VARCHAR(255) DEFAULT 'MUR',
    category            VARCHAR(255),
    subcategory         VARCHAR(255),
    attributes          JSONB DEFAULT '{}',
    tags                TEXT[] DEFAULT '{}',
    image_urls          JSONB DEFAULT '[]',
    primary_image_url   TEXT,
    vendor_name         VARCHAR(255),
    vendor_no           VARCHAR(255),
    bc_company          VARCHAR(255),
    bc_location         VARCHAR(255),
    remaining_qty       DECIMAL(12,2),
    lot_no              VARCHAR(255),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_new              BOOLEAN NOT NULL DEFAULT FALSE,
    is_expiring_soon    BOOLEAN NOT NULL DEFAULT FALSE,
    expiry_date         DATE,
    bc_last_synced_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_products_brand_id ON products (brand_id);
CREATE INDEX idx_products_bc_item_no ON products (bc_item_no);
CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_sku ON products (sku);
CREATE INDEX idx_products_is_active ON products (is_active);
CREATE INDEX idx_products_tags ON products USING GIN (tags);

-- ── Campaigns ───────────────────────────────────────────────────
CREATE TABLE campaigns (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    objective       VARCHAR(100) CHECK (objective IN (
                        'awareness', 'engagement', 'traffic', 'conversions',
                        'product_launch', 'seasonal', 'event', 'other'
                    )),
    status          VARCHAR(50) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'active', 'paused', 'completed', 'archived')),
    start_date      DATE,
    end_date        DATE,
    budget          JSONB DEFAULT '{}',
    target_channels TEXT[] DEFAULT '{}',
    target_audience JSONB DEFAULT '{}',
    kpis            JSONB DEFAULT '{}',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_campaigns_brand_id ON campaigns (brand_id);
CREATE INDEX idx_campaigns_status ON campaigns (status);
CREATE INDEX idx_campaigns_start_date ON campaigns (start_date);
CREATE INDEX idx_campaigns_end_date ON campaigns (end_date);
CREATE INDEX idx_campaigns_created_by ON campaigns (created_by);

-- ── Calendar Items ──────────────────────────────────────────────
CREATE TABLE calendar_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    item_type       VARCHAR(50) NOT NULL
                    CHECK (item_type IN ('post', 'story', 'reel', 'carousel',
                                          'article', 'newsletter', 'ad', 'event', 'other')),
    channel         VARCHAR(50) NOT NULL
                    CHECK (channel IN ('instagram', 'facebook', 'linkedin',
                                        'youtube', 'tiktok', 'x', 'website_blog', 'teams')),
    scheduled_at    TIMESTAMPTZ,
    published_at    TIMESTAMPTZ,
    status          VARCHAR(50) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'working', 'in_review', 'reworking',
                                       'approved', 'scheduled', 'publishing', 'published', 'failed')),
    assigned_to     UUID REFERENCES users(id),
    pillar          VARCHAR(100),
    theme           VARCHAR(255),
    target_audience VARCHAR(255),
    weekly_sub_theme VARCHAR(255),
    content_brief   TEXT,
    visual_direction TEXT,
    cta_type        VARCHAR(50),
    product_ids     UUID[] DEFAULT '{}',
    tags            TEXT[] DEFAULT '{}',
    priority        SMALLINT DEFAULT 0 CHECK (priority BETWEEN 0 AND 5),
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_calendar_items_brand_id ON calendar_items (brand_id);
CREATE INDEX idx_calendar_items_campaign_id ON calendar_items (campaign_id);
CREATE INDEX idx_calendar_items_channel ON calendar_items (channel);
CREATE INDEX idx_calendar_items_pillar ON calendar_items (pillar);
CREATE INDEX idx_calendar_items_theme ON calendar_items (theme);
CREATE INDEX idx_calendar_items_brand_scheduled ON calendar_items (brand_id, scheduled_at DESC);
CREATE INDEX idx_calendar_items_status ON calendar_items (status);
CREATE INDEX idx_calendar_items_scheduled_at ON calendar_items (scheduled_at);
CREATE INDEX idx_calendar_items_assigned_to ON calendar_items (assigned_to);
CREATE INDEX idx_calendar_items_created_by ON calendar_items (created_by);

-- ── Content ─────────────────────────────────────────────────────
CREATE TABLE content (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    calendar_item_id    UUID NOT NULL REFERENCES calendar_items(id) ON DELETE CASCADE,
    brand_id            UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    version             INTEGER NOT NULL DEFAULT 1,
    body_text           TEXT,
    headline            VARCHAR(255),
    caption             TEXT,
    hashtags            TEXT[] DEFAULT '{}',
    cta_text            VARCHAR(255),
    cta_url             TEXT,
    image_urls          JSONB DEFAULT '[]',
    video_url           TEXT,
    media_assets        JSONB DEFAULT '[]',
    platform_metadata   JSONB DEFAULT '{}',
    platform_post_id    VARCHAR(255),
    ai_generated        BOOLEAN NOT NULL DEFAULT FALSE,
    ai_model            VARCHAR(255),
    ai_prompt_version   UUID,
    generation_metadata JSONB DEFAULT '{}',
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_content_calendar_item_id ON content (calendar_item_id);
CREATE INDEX idx_content_brand_id ON content (brand_id);
CREATE INDEX idx_content_is_current ON content (is_current);
CREATE INDEX idx_content_platform_post_id ON content (platform_post_id);
CREATE INDEX idx_content_created_by ON content (created_by);

-- ── Approvals ───────────────────────────────────────────────────
CREATE TABLE approvals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id      UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
    calendar_item_id UUID NOT NULL REFERENCES calendar_items(id) ON DELETE CASCADE,
    reviewer_id     UUID NOT NULL REFERENCES users(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'revision_requested')),
    feedback        TEXT,
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_approvals_content_id ON approvals (content_id);
CREATE INDEX idx_approvals_calendar_item_id ON approvals (calendar_item_id);
CREATE INDEX idx_approvals_reviewer_id ON approvals (reviewer_id);
CREATE INDEX idx_approvals_status ON approvals (status);

-- ── Prompt Versions ─────────────────────────────────────────────
CREATE TABLE prompt_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL,
    category        VARCHAR(100) NOT NULL
                    CHECK (category IN ('content_generation', 'image_generation',
                                         'competitor_analysis', 'trend_research',
                                         'adaptation', 'engagement', 'other')),
    template        TEXT NOT NULL,
    variables       JSONB DEFAULT '[]',
    version         INTEGER NOT NULL DEFAULT 1,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    performance_score NUMERIC(5,4),
    a_b_group       VARCHAR(1) CHECK (a_b_group IN ('A', 'B')),
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (slug, version)
);

CREATE INDEX idx_prompt_versions_slug ON prompt_versions (slug);
CREATE INDEX idx_prompt_versions_category ON prompt_versions (category);
CREATE INDEX idx_prompt_versions_is_active ON prompt_versions (is_active);

-- ── Agent Runs ──────────────────────────────────────────────────
CREATE TABLE agent_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type      VARCHAR(100) NOT NULL,
    trigger         VARCHAR(100) NOT NULL
                    CHECK (trigger IN ('scheduled', 'manual', 'event', 'webhook')),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    input_payload   JSONB DEFAULT '{}',
    output_payload  JSONB DEFAULT '{}',
    error_message   TEXT,
    tokens_used     INTEGER DEFAULT 0,
    cost_usd        NUMERIC(10,6) DEFAULT 0,
    duration_ms     INTEGER,
    prompt_version_id UUID REFERENCES prompt_versions(id) ON DELETE SET NULL,
    brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    initiated_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_runs_agent_type ON agent_runs (agent_type);
CREATE INDEX idx_agent_runs_status ON agent_runs (status);
CREATE INDEX idx_agent_runs_brand_id ON agent_runs (brand_id);
CREATE INDEX idx_agent_runs_initiated_by ON agent_runs (initiated_by);
CREATE INDEX idx_agent_runs_created_at ON agent_runs (created_at DESC);

-- ── Engagement Metrics ──────────────────────────────────────────
CREATE TABLE engagement_metrics (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id          UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
    calendar_item_id    UUID NOT NULL REFERENCES calendar_items(id) ON DELETE CASCADE,
    brand_id            UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    channel             VARCHAR(50) NOT NULL,
    impressions         INTEGER DEFAULT 0,
    reach               INTEGER DEFAULT 0,
    likes               INTEGER DEFAULT 0,
    comments            INTEGER DEFAULT 0,
    shares              INTEGER DEFAULT 0,
    saves               INTEGER DEFAULT 0,
    clicks              INTEGER DEFAULT 0,
    video_views         INTEGER DEFAULT 0,
    engagement_rate     NUMERIC(8,4),
    sentiment_score     NUMERIC(5,4),
    raw_metrics         JSONB DEFAULT '{}',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_engagement_metrics_content_id ON engagement_metrics (content_id);
CREATE INDEX idx_engagement_metrics_calendar_item_id ON engagement_metrics (calendar_item_id);
CREATE INDEX idx_engagement_metrics_brand_id ON engagement_metrics (brand_id);
CREATE INDEX idx_engagement_metrics_channel ON engagement_metrics (channel);
CREATE INDEX idx_engagement_metrics_fetched_at ON engagement_metrics (fetched_at DESC);

-- ── Competitors ─────────────────────────────────────────────────
CREATE TABLE competitors (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    brand_id        UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    website_url     TEXT,
    social_handles  JSONB DEFAULT '{}',
    description     TEXT,
    monitoring_config JSONB DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_competitors_brand_id ON competitors (brand_id);
CREATE INDEX idx_competitors_is_active ON competitors (is_active);

-- ── Adaptations (multi-channel content variants) ────────────────
CREATE TABLE adaptations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_content_id   UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
    target_channel      VARCHAR(50) NOT NULL
                        CHECK (target_channel IN ('instagram', 'facebook', 'linkedin',
                                                    'youtube', 'tiktok', 'x', 'website_blog', 'teams')),
    adapted_text        TEXT,
    adapted_headline    VARCHAR(500),
    adapted_hashtags    TEXT[] DEFAULT '{}',
    adapted_media       JSONB DEFAULT '[]',
    adaptation_notes    TEXT,
    ai_model            VARCHAR(255),
    status              VARCHAR(50) NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'working', 'in_review', 'reworking',
                                           'approved', 'scheduled', 'published', 'failed')),
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_adaptations_source_content_id ON adaptations (source_content_id);
CREATE INDEX idx_adaptations_target_channel ON adaptations (target_channel);
CREATE INDEX idx_adaptations_status ON adaptations (status);

-- ── Scheduled Job Log ───────────────────────────────────────────
CREATE TABLE scheduled_job_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_name        VARCHAR(255) NOT NULL,
    job_type        VARCHAR(100) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'started'
                    CHECK (status IN ('started', 'completed', 'failed')),
    details         JSONB DEFAULT '{}',
    error_message   TEXT,
    duration_ms     INTEGER,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scheduled_job_log_job_name ON scheduled_job_log (job_name);
CREATE INDEX idx_scheduled_job_log_job_type ON scheduled_job_log (job_type);
CREATE INDEX idx_scheduled_job_log_status ON scheduled_job_log (status);
CREATE INDEX idx_scheduled_job_log_started_at ON scheduled_job_log (started_at DESC);

-- ── Audit Log ───────────────────────────────────────────────────
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    action          VARCHAR(100) NOT NULL,
    entity_type     VARCHAR(100) NOT NULL,
    entity_id       UUID,
    old_values      JSONB,
    new_values      JSONB,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user_id ON audit_log (user_id);
CREATE INDEX idx_audit_log_action ON audit_log (action);
CREATE INDEX idx_audit_log_entity_type ON audit_log (entity_type);
CREATE INDEX idx_audit_log_entity_id ON audit_log (entity_id);
CREATE INDEX idx_audit_log_created_at ON audit_log (created_at DESC);

-- ── Notifications ───────────────────────────────────────────────
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    body            TEXT,
    notification_type VARCHAR(50) NOT NULL
                    CHECK (notification_type IN ('info', 'success', 'warning', 'error',
                                                   'approval_request', 'approval_decision',
                                                   'content_ready', 'publish_success',
                                                   'publish_failure', 'system')),
    channel         VARCHAR(50) NOT NULL DEFAULT 'in_app'
                    CHECK (channel IN ('in_app', 'email', 'slack', 'push')),
    reference_type  VARCHAR(100),
    reference_id    UUID,
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    read_at         TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_id ON notifications (user_id);
CREATE INDEX idx_notifications_type ON notifications (notification_type);
CREATE INDEX idx_notifications_is_read ON notifications (is_read);
CREATE INDEX idx_notifications_user_unread ON notifications (user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_notifications_created_at ON notifications (created_at DESC);

-- ── AI Model Categories (use cases) ───────────────────────────────
CREATE TABLE ai_model_categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(50) UNIQUE NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Available AI Models (discovered from API) ─────────────────────
CREATE TABLE ai_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        VARCHAR(50) NOT NULL DEFAULT 'openai',
    model_id        VARCHAR(255) NOT NULL,
    display_name    VARCHAR(255),
    category_id     UUID REFERENCES ai_model_categories(id),
    is_available    BOOLEAN DEFAULT true,
    capabilities    JSONB DEFAULT '{}',
    discovered_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(provider, model_id)
);

CREATE INDEX idx_ai_models_provider ON ai_models (provider);
CREATE INDEX idx_ai_models_category_id ON ai_models (category_id);
CREATE INDEX idx_ai_models_is_available ON ai_models (is_available);

-- ── Active Model Selections (admin picks per category) ────────────
CREATE TABLE ai_model_selections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_slug   VARCHAR(50) NOT NULL REFERENCES ai_model_categories(slug),
    model_id        UUID REFERENCES ai_models(id) NOT NULL,
    is_active       BOOLEAN DEFAULT true,
    priority        INT DEFAULT 0,
    set_by          UUID REFERENCES users(id),
    set_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(category_slug, model_id)
);

CREATE INDEX idx_ai_model_selections_category ON ai_model_selections (category_slug);
CREATE INDEX idx_ai_model_selections_active ON ai_model_selections (is_active);

-- Seed AI model categories
INSERT INTO ai_model_categories (slug, display_name, description) VALUES
    ('text',       'Text / Chat',            'Language models for text generation, chat, reasoning'),
    ('text-fast',  'Text / Chat (Fast)',      'Faster, cheaper language models for simple tasks'),
    ('image',      'Image Generation',        'Models for generating images from text prompts'),
    ('embedding',  'Text Embedding',          'Models for generating vector embeddings'),
    ('tts',        'Text-to-Speech',          'Models for converting text to audio'),
    ('stt',        'Speech-to-Text',          'Models for transcribing audio to text'),
    ('video',      'Video Generation',        'Models for generating video content'),
    ('moderation', 'Content Moderation',      'Models for detecting harmful content'),
    ('vision',     'Vision / Image Analysis', 'Models for analyzing and understanding images');

-- ── App Settings ──────────────────────────────────────────────────
CREATE TABLE app_settings (
    key VARCHAR(255) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default settings
INSERT INTO app_settings (key, value) VALUES
    ('scheduler_timezone', '"Indian/Mauritius"'),
    ('morning_schedule_hour', '6'),
    ('morning_schedule_minute', '0'),
    ('publish_check_interval_minutes', '15'),
    ('engagement_pull_interval_hours', '6'),
    ('bc_sync_interval_hours', '6'),
    ('max_daily_posts', '3'),
    ('auto_approve_threshold', '90'),
    ('default_channels', '["instagram", "facebook", "linkedin", "youtube", "tiktok", "x", "website_blog", "teams"]'),
    ('notification_channels', '["teams", "portal"]'),
    ('content_generation_days_ahead', '7');

-- ── Updated-at trigger function ─────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at triggers to all tables with updated_at column
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'updated_at'
          AND table_schema = 'public'
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trigger_updated_at BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();',
            tbl
        );
    END LOOP;
END;
$$;
