# MARKAI — AI Coding Agent Master Implementation Prompt

## Project Identity

**Project:** MARKAI — Autonomous AI Marketing Operating System
**Owner:** Chemtech Group (Damien Adam)
**Brands:** Healthspan, Naturespan, TheShop.mu, Biopeak Mauritius (+ future brands)
**Agent Target:** VS Code with Cursor / Claude Code / Windsurf

---

## Critical Rules for the Coding Agent

1. **Never hardcode data that can be dynamic.** All brand info, table names, API keys, credentials come from `.env` or database.
2. **Never generate fake product images.** AI backgrounds are fine. Product images must come from: (a) Business Central product image, (b) supplier website, (c) web search — in that priority order.
3. **All AI calls go through LiteLLM.** Never import `openai` directly in application code. Always call via the LiteLLM proxy at `LITELLM_BASE_URL`.
4. **Every workflow is a separate LangGraph graph.** No monolithic agents.
5. **All configuration is admin-portal-driven.** No code changes needed post-deployment.
6. **Use Microsoft Entra ID for all auth.** SSO via OIDC. The tenant, client ID, and secret are in `.env`.
7. **Business Central data comes via Fabric Lakehouse** (`lh_bronze`) accessed through Power BI REST API with a separate Entra ID app. Table names are in `.env`.
8. **Use latest stable versions** of all packages as of March 2026.
9. **All services run in Docker Compose** behind Traefik reverse proxy.
10. **TypeScript for frontend (Next.js), Python for backend (FastAPI, LangGraph, LiteLLM).**
11. **n8n is ONLY for social platform API publishing.** All scheduling, engagement pulling, error handling, and internal orchestration lives in FastAPI as background tasks using APScheduler.

---

## Technology Stack (Final)

| Component | Technology | Version |
|-----------|-----------|---------|
| Frontend | Next.js (App Router) | 15.x |
| Backend API | FastAPI + APScheduler | 0.115+ |
| Agent Runtime | LangGraph | 1.1+ |
| AI Gateway | LiteLLM Proxy | 1.x |
| AI Provider | OpenAI (via LiteLLM) | gpt-4o, dall-e-3, text-embedding-3-small |
| Event Bus | NATS JetStream | 2.x |
| Relational DB | PostgreSQL | 16 |
| Vector DB | Qdrant | 1.x |
| Object Storage | MinIO | latest |
| Cache | Valkey | 8.x |
| Auth/IAM | Microsoft Entra ID | OIDC/OAuth2 |
| Social Publishing | n8n (3 workflows only) | 1.x self-hosted |
| Browser | Playwright | 1.x |
| Eval | Promptfoo | latest |
| Observability | OpenTelemetry + Grafana + Prometheus + Loki | latest |
| Agent Tracing | LangSmith | latest |
| Reverse Proxy | Traefik | 3.x |
| BC Data Access | Power BI REST API → Fabric Lakehouse lh_bronze | v1.0 |

---

## Repository Structure

```
markai/
├── docker-compose.yml
├── docker-compose.override.yml          # Local dev overrides
├── .env.example
├── traefik/
│   └── traefik.yml
│
├── frontend/                             # Next.js 15 App Router
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx                # Root layout with auth provider
│   │   │   ├── page.tsx                  # Dashboard home / mission control
│   │   │   ├── brands/
│   │   │   │   ├── page.tsx              # Brand list
│   │   │   │   ├── [id]/
│   │   │   │   │   ├── page.tsx          # Brand detail/edit
│   │   │   │   │   ├── research/page.tsx
│   │   │   │   │   ├── strategy/page.tsx
│   │   │   │   │   └── performance/page.tsx
│   │   │   │   └── new/page.tsx          # Create brand
│   │   │   ├── content/
│   │   │   │   ├── page.tsx              # Content studio (Kanban)
│   │   │   │   ├── [id]/page.tsx         # Content detail/editor
│   │   │   │   └── calendar/page.tsx     # Calendar view
│   │   │   ├── approvals/
│   │   │   │   └── page.tsx              # Pending approvals queue
│   │   │   ├── intelligence/
│   │   │   │   ├── page.tsx              # Research & competitor intel
│   │   │   │   └── products/page.tsx     # BC product intelligence
│   │   │   ├── analytics/
│   │   │   │   └── page.tsx              # Performance dashboards
│   │   │   ├── learning/
│   │   │   │   └── page.tsx              # System learning & adaptation
│   │   │   ├── prompts/
│   │   │   │   └── page.tsx              # Prompt lab
│   │   │   ├── providers/
│   │   │   │   └── page.tsx              # AI provider config
│   │   │   ├── system/
│   │   │   │   ├── page.tsx              # System health & workflows
│   │   │   │   └── audit/page.tsx        # Audit log
│   │   │   ├── settings/
│   │   │   │   ├── page.tsx              # General settings
│   │   │   │   └── users/page.tsx        # User & role management
│   │   │   └── api/
│   │   │       └── auth/
│   │   │           └── [...nextauth]/route.ts  # NextAuth.js Entra ID
│   │   ├── components/
│   │   │   ├── ui/                       # shadcn/ui primitives
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   └── BrandSwitcher.tsx
│   │   │   ├── content/
│   │   │   │   ├── ContentCard.tsx
│   │   │   │   ├── ContentEditor.tsx
│   │   │   │   ├── KanbanBoard.tsx
│   │   │   │   ├── CalendarView.tsx
│   │   │   │   └── AssetPreview.tsx
│   │   │   ├── approval/
│   │   │   │   ├── ApprovalActions.tsx
│   │   │   │   └── ApprovalHistory.tsx
│   │   │   ├── brand/
│   │   │   │   ├── BrandForm.tsx
│   │   │   │   ├── BrandCard.tsx
│   │   │   │   └── CompetitorTracker.tsx
│   │   │   ├── analytics/
│   │   │   │   ├── EngagementChart.tsx
│   │   │   │   ├── PerformanceGrid.tsx
│   │   │   │   └── PostingHeatmap.tsx
│   │   │   └── system/
│   │   │       ├── WorkflowMonitor.tsx
│   │   │       ├── ServiceHealth.tsx
│   │   │       └── QueueDepth.tsx
│   │   ├── lib/
│   │   │   ├── api.ts                    # FastAPI client (fetch wrapper)
│   │   │   ├── auth.ts                   # NextAuth config for Entra ID
│   │   │   └── utils.ts
│   │   └── types/
│   │       └── index.ts                  # Shared TypeScript types
│   └── Dockerfile
│
├── backend/                              # FastAPI
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                     # DB migrations
│   ├── app/
│   │   ├── main.py                       # FastAPI app entry + APScheduler setup
│   │   ├── config.py                     # Settings from .env
│   │   ├── deps.py                       # Dependency injection
│   │   ├── auth/
│   │   │   ├── entra.py                  # Entra ID JWT validation
│   │   │   ├── permissions.py            # RBAC decorators
│   │   │   └── models.py                 # User, Role models
│   │   ├── models/
│   │   │   ├── brand.py
│   │   │   ├── content.py
│   │   │   ├── campaign.py
│   │   │   ├── calendar_item.py
│   │   │   ├── approval.py
│   │   │   ├── prompt_version.py
│   │   │   ├── agent_run.py
│   │   │   ├── engagement.py
│   │   │   ├── adaptation.py
│   │   │   ├── competitor.py
│   │   │   ├── product.py                # BC product sync
│   │   │   └── base.py                   # SQLAlchemy base
│   │   ├── schemas/                      # Pydantic schemas (mirror models)
│   │   │   └── ...
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── brands.py
│   │   │   │   ├── content.py
│   │   │   │   ├── approvals.py
│   │   │   │   ├── calendar.py
│   │   │   │   ├── campaigns.py
│   │   │   │   ├── analytics.py
│   │   │   │   ├── products.py           # BC product endpoints
│   │   │   │   ├── prompts.py
│   │   │   │   ├── providers.py
│   │   │   │   ├── system.py
│   │   │   │   ├── users.py
│   │   │   │   ├── webhooks.py           # n8n publish result callbacks only
│   │   │   │   └── intelligence.py
│   │   │   └── router.py
│   │   ├── services/
│   │   │   ├── brand_service.py
│   │   │   ├── content_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── calendar_service.py
│   │   │   ├── product_service.py        # BC/Fabric data service
│   │   │   ├── analytics_service.py
│   │   │   ├── prompt_service.py
│   │   │   ├── notification_service.py   # Slack + email + in-app (replaces n8n error handler)
│   │   │   ├── nats_service.py           # NATS publish/subscribe
│   │   │   ├── minio_service.py          # File upload/download
│   │   │   ├── qdrant_service.py         # Vector ops
│   │   │   ├── fabric_service.py         # Power BI / Fabric Lakehouse client
│   │   │   ├── engagement_service.py     # Pull engagement from social APIs directly
│   │   │   └── publish_service.py        # Dispatch publish jobs to n8n webhooks
│   │   └── scheduler/                    # APScheduler background tasks
│   │       ├── __init__.py               # Scheduler setup, job registration
│   │       ├── morning_jobs.py           # 6 AM: BC sync + engagement pull + evaluation trigger
│   │       ├── publish_checker.py        # Every 15 min: check for due content, dispatch to n8n
│   │       ├── engagement_puller.py      # Pull engagement metrics from social APIs
│   │       └── bc_sync.py                # Periodic BC/Fabric data sync
│   └── Dockerfile
│
├── agents/                               # LangGraph agent workers
│   ├── pyproject.toml
│   ├── shared/
│   │   ├── config.py
│   │   ├── llm.py                        # LiteLLM client wrapper
│   │   ├── tools/
│   │   │   ├── web_search.py
│   │   │   ├── browser.py                # Playwright tool calls
│   │   │   ├── image_search.py           # Product image finder
│   │   │   ├── storage.py                # MinIO read/write
│   │   │   ├── database.py               # PostgreSQL read/write
│   │   │   ├── vector.py                 # Qdrant search/index
│   │   │   ├── fabric.py                 # Fabric Lakehouse query tool
│   │   │   └── social.py                 # Social platform data tools
│   │   ├── state.py
│   │   └── nats_consumer.py              # NATS JetStream consumer base
│   ├── workflows/
│   │   ├── research/
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   ├── strategy/
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   ├── planning/
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   ├── content/
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   ├── image_sourcing.py         # Real product image pipeline
│   │   │   └── state.py
│   │   ├── evaluation/
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   ├── product_intel/
│   │   │   ├── graph.py                  # BC product discovery workflow
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   └── adaptation/
│   │       ├── graph.py
│   │       ├── nodes.py
│   │       └── state.py
│   ├── worker.py                         # Main worker entry (subscribes to NATS)
│   └── Dockerfile
│
├── browser-worker/                       # Playwright service
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                       # FastAPI micro-service
│   │   ├── capture.py                    # Screenshot, page extract
│   │   ├── product_image.py              # Product image scraper
│   │   └── social_scraper.py             # Social page scraper
│   └── Dockerfile
│
├── litellm/
│   ├── config.yaml
│   └── Dockerfile
│
├── notifications/                        # Notification micro-service
│   ├── app/
│   │   ├── main.py
│   │   ├── email.py
│   │   ├── slack.py                      # Slack webhook sender
│   │   └── portal.py                     # In-app notifications via SSE
│   └── Dockerfile
│
├── eval/                                 # Promptfoo configs
│   ├── promptfooconfig.yaml
│   ├── prompts/
│   └── tests/
│
├── observability/
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── dashboards/
│   │   │   └── datasources/
│   │   └── grafana.ini
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── loki/
│   │   └── loki-config.yaml
│   └── otel-collector/
│       └── otel-collector-config.yaml
│
├── db/
│   └── init.sql
│
└── scripts/
    ├── seed-dev.py
    └── bc-table-discovery.py
```

---

## Environment Variables (.env.example)

```bash
# ============================================================
# MARKAI Environment Configuration
# ============================================================

# --- General ---
MARKAI_ENV=development
MARKAI_DOMAIN=markai.example.com
SECRET_KEY=change-me-to-a-random-string

# --- Microsoft Entra ID (SSO) ---
AZURE_AD_TENANT_ID=your-tenant-id
AZURE_AD_CLIENT_ID=your-markai-app-client-id
AZURE_AD_CLIENT_SECRET=your-markai-app-client-secret
NEXTAUTH_URL=https://markai.example.com
NEXTAUTH_SECRET=change-me-random-secret

# --- Microsoft Entra ID (Fabric / Power BI) ---
FABRIC_TENANT_ID=your-tenant-id
FABRIC_CLIENT_ID=your-fabric-app-client-id
FABRIC_CLIENT_SECRET=your-fabric-app-client-secret
FABRIC_WORKSPACE_ID=your-fabric-workspace-id
FABRIC_DATASET_ID=your-dataset-id
FABRIC_LAKEHOUSE_NAME=lh_bronze

# --- Business Central Tables (discovered after initial sync) ---
BC_TABLE_ITEMS=items
BC_TABLE_ITEM_CATEGORIES=item_categories
BC_TABLE_VENDORS=vendors
BC_TABLE_ITEM_ATTRIBUTES=item_attributes
BC_TABLE_ITEM_PICTURES=item_pictures
BC_TABLE_SALES_PRICES=sales_prices
BC_TABLE_ITEM_LEDGER_ENTRIES=item_ledger_entries
# Add more tables as discovered

# --- OpenAI (via LiteLLM) ---
OPENAI_API_KEY=sk-your-openai-key

# --- LiteLLM ---
LITELLM_BASE_URL=http://litellm:4000
LITELLM_MASTER_KEY=sk-markai-litellm-key

# --- PostgreSQL ---
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=markai
POSTGRES_USER=markai
POSTGRES_PASSWORD=change-me

# --- Qdrant ---
QDRANT_HOST=qdrant
QDRANT_PORT=6333

# --- MinIO ---
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=markai-minio
MINIO_SECRET_KEY=change-me
MINIO_BUCKET=markai-assets

# --- Valkey ---
VALKEY_HOST=valkey
VALKEY_PORT=6379

# --- NATS ---
NATS_URL=nats://nats:4222

# --- n8n (social publishing only) ---
N8N_BASE_URL=http://n8n:5678
N8N_WEBHOOK_BASE=https://n8n.example.com/webhook

# --- Playwright Browser Worker ---
BROWSER_WORKER_URL=http://browser-worker:8001

# --- LangSmith (optional) ---
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-key
LANGCHAIN_PROJECT=markai

# --- Notifications ---
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=notifications@example.com
SMTP_PASSWORD=change-me
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx

# --- Social Platform API Keys (for engagement pulling in FastAPI) ---
META_ACCESS_TOKEN=your-long-lived-page-token
META_PAGE_ID=your-facebook-page-id
META_INSTAGRAM_ACCOUNT_ID=your-instagram-business-account-id
LINKEDIN_ACCESS_TOKEN=your-linkedin-token
LINKEDIN_ORG_ID=your-linkedin-org-urn

# --- Scheduler ---
SCHEDULER_TIMEZONE=Indian/Mauritius
MORNING_SCHEDULE_HOUR=6
MORNING_SCHEDULE_MINUTE=0
PUBLISH_CHECK_INTERVAL_MINUTES=15
ENGAGEMENT_PULL_INTERVAL_HOURS=6
BC_SYNC_INTERVAL_HOURS=6
```

---

## Phase 1: Foundation Infrastructure (Week 1-2)

### 1.1 Docker Compose

Create `docker-compose.yml` with all services:

**Services to define:**
- `traefik` — reverse proxy, ports 80/443, auto-TLS via Let's Encrypt
- `postgres` — PostgreSQL 16, volume mount, init script
- `qdrant` — Qdrant latest, volume mount, port 6333
- `minio` — MinIO latest, volume mount, ports 9000/9001
- `valkey` — Valkey 8, port 6379
- `nats` — NATS with JetStream enabled (`-js`), ports 4222/8222
- `litellm` — LiteLLM proxy, mount config.yaml, port 4000
- `n8n` — n8n self-hosted, volume mount, port 5678 **(social publishing only)**
- `backend` — FastAPI, build from `./backend`, port 8000
- `frontend` — Next.js, build from `./frontend`, port 3000
- `agents` — LangGraph worker, build from `./agents`
- `browser-worker` — Playwright service, build from `./browser-worker`, port 8001
- `notifications` — Notification service, build from `./notifications`
- `grafana` — Grafana, port 3001, provisioned dashboards
- `prometheus` — Prometheus, port 9090
- `loki` — Loki, port 3100
- `otel-collector` — OpenTelemetry Collector

**Network:** Single Docker network `markai-net`.

**Traefik labels** for subdomain routing:
- `markai.example.com` → frontend
- `api.markai.example.com` → backend
- `n8n.markai.example.com` → n8n
- `grafana.markai.example.com` → grafana

### 1.2 PostgreSQL Schema

Create initial migration via Alembic. Core tables:

```sql
-- Users & Auth
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entra_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Brands
CREATE TABLE brands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    website VARCHAR(500),
    description TEXT,
    tone_settings JSONB DEFAULT '{}',
    visual_identity JSONB DEFAULT '{}',
    target_audiences JSONB DEFAULT '[]',
    content_pillars JSONB DEFAULT '[]',
    excluded_topics JSONB DEFAULT '[]',
    brand_safety_rules JSONB DEFAULT '[]',
    social_links JSONB DEFAULT '{}',
    social_credentials JSONB DEFAULT '{}',       -- Platform tokens/IDs per brand
    posting_cadence JSONB DEFAULT '{}',
    approval_chain JSONB DEFAULT '{}',
    competitor_urls JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT true,
    is_bc_linked BOOLEAN DEFAULT false,
    bc_vendor_filter JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Products (synced from Business Central via Fabric)
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bc_item_no VARCHAR(50) UNIQUE NOT NULL,
    brand_id UUID REFERENCES brands(id),
    name VARCHAR(500) NOT NULL,
    description TEXT,
    category VARCHAR(255),
    vendor_name VARCHAR(255),
    vendor_no VARCHAR(50),
    unit_price DECIMAL(12,2),
    image_url VARCHAR(1000),
    image_source VARCHAR(50),                    -- 'bc', 'supplier', 'websearch'
    image_stored_path VARCHAR(500),
    attributes JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    is_new BOOLEAN DEFAULT false,
    is_expiring_soon BOOLEAN DEFAULT false,
    expiry_date DATE,
    last_synced_at TIMESTAMPTZ,
    last_promoted_at TIMESTAMPTZ,
    promotion_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Campaigns
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,
    content_pillars JSONB DEFAULT '[]',
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Calendar Items
CREATE TABLE calendar_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) NOT NULL,
    campaign_id UUID REFERENCES campaigns(id),
    product_id UUID REFERENCES products(id),
    title VARCHAR(500) NOT NULL,
    content_type VARCHAR(50) NOT NULL,
    channel VARCHAR(50) NOT NULL,
    scheduled_at TIMESTAMPTZ,
    content_pillar VARCHAR(255),
    cta_type VARCHAR(100),
    asset_requirements JSONB DEFAULT '[]',
    notes TEXT,
    status VARCHAR(50) DEFAULT 'planned',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Content
CREATE TABLE content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_item_id UUID REFERENCES calendar_items(id),
    brand_id UUID REFERENCES brands(id) NOT NULL,
    version INT DEFAULT 1,
    hook TEXT,
    caption TEXT,
    hashtags JSONB DEFAULT '[]',
    cta TEXT,
    slides JSONB DEFAULT '[]',
    image_prompt TEXT,
    product_image_url VARCHAR(1000),
    product_image_source VARCHAR(50),
    generated_image_url VARCHAR(1000),
    video_brief TEXT,
    assets JSONB DEFAULT '[]',
    platform_adaptations JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'draft',
    rejection_reason TEXT,
    feedback_history JSONB DEFAULT '[]',
    confidence_score FLOAT,
    generation_metadata JSONB DEFAULT '{}',
    published_at TIMESTAMPTZ,
    platform_post_id VARCHAR(255),              -- ID returned by social platform after publish
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Approvals
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    requested_by UUID REFERENCES users(id),
    assigned_to UUID REFERENCES users(id),
    status VARCHAR(50) DEFAULT 'pending',
    decision_at TIMESTAMPTZ,
    comments TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prompt Versions
CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow VARCHAR(100) NOT NULL,
    step VARCHAR(100) NOT NULL,
    version INT NOT NULL,
    content TEXT NOT NULL,
    variables JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT false,
    ab_test_weight FLOAT DEFAULT 0,
    performance_metrics JSONB DEFAULT '{}',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workflow, step, version)
);

-- Agent Runs
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow VARCHAR(100) NOT NULL,
    brand_id UUID REFERENCES brands(id),
    status VARCHAR(50) DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    state_snapshot JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    trigger_event VARCHAR(255),
    langsmith_run_id VARCHAR(255)
);

-- Engagement Metrics
CREATE TABLE engagement_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id UUID REFERENCES content(id) NOT NULL,
    platform VARCHAR(50) NOT NULL,
    impressions INT DEFAULT 0,
    reach INT DEFAULT 0,
    likes INT DEFAULT 0,
    comments INT DEFAULT 0,
    shares INT DEFAULT 0,
    saves INT DEFAULT 0,
    clicks INT DEFAULT 0,
    video_views INT DEFAULT 0,
    watch_time_seconds INT DEFAULT 0,
    completion_rate FLOAT,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    raw_data JSONB DEFAULT '{}'
);

-- Competitors
CREATE TABLE competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    website VARCHAR(500),
    social_links JSONB DEFAULT '{}',
    last_analyzed_at TIMESTAMPTZ,
    analysis_summary TEXT,
    content_patterns JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Adaptations
CREATE TABLE adaptations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id),
    tier VARCHAR(20) NOT NULL,
    category VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    confidence_score FLOAT NOT NULL,
    data_points INT,
    proposed_change JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'proposed',
    applied_at TIMESTAMPTZ,
    impact_after JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled Jobs Log (tracks APScheduler executions)
CREATE TABLE scheduled_job_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,                 -- started, completed, failed
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

-- Audit Log
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id UUID,
    details JSONB DEFAULT '{}',
    ip_address VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notifications
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    entity_type VARCHAR(100),
    entity_id UUID,
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 1.3 LiteLLM Configuration

Create `litellm/config.yaml`:

```yaml
model_list:
  - model_name: "markai-text"
    litellm_params:
      model: "openai/gpt-4o"
      api_key: "os.environ/OPENAI_API_KEY"
  - model_name: "markai-fast"
    litellm_params:
      model: "openai/gpt-4o-mini"
      api_key: "os.environ/OPENAI_API_KEY"
  - model_name: "markai-embed"
    litellm_params:
      model: "openai/text-embedding-3-small"
      api_key: "os.environ/OPENAI_API_KEY"
  - model_name: "markai-image"
    litellm_params:
      model: "openai/dall-e-3"
      api_key: "os.environ/OPENAI_API_KEY"
  # --- STANDBY (uncomment to activate) ---
  # - model_name: "markai-text"
  #   litellm_params:
  #     model: "anthropic/claude-sonnet-4-20250514"
  #     api_key: "os.environ/ANTHROPIC_API_KEY"
  # - model_name: "markai-text-local"
  #   litellm_params:
  #     model: "ollama/llama3"
  #     api_base: "http://gpu-host:11434"

general_settings:
  master_key: "os.environ/LITELLM_MASTER_KEY"

litellm_settings:
  drop_params: true
  set_verbose: false
  cache: true
  cache_params:
    type: "redis"
    host: "os.environ/VALKEY_HOST"
    port: "os.environ/VALKEY_PORT"
```

### 1.4 NATS JetStream Streams

Bootstrap script creates these on startup:

```python
STREAMS = {
    "BRAND":      {"subjects": ["brand.>"]},
    "RESEARCH":   {"subjects": ["research.>"]},
    "STRATEGY":   {"subjects": ["strategy.>"]},
    "CONTENT":    {"subjects": ["content.>"]},
    "PUBLISH":    {"subjects": ["publish.>"]},
    "ENGAGEMENT": {"subjects": ["engagement.>"]},
    "EVALUATION": {"subjects": ["evaluation.>"]},
    "PRODUCT":    {"subjects": ["product.>"]},
}
```

### 1.5 APScheduler Setup (Replaces n8n Scheduling)

In `backend/app/scheduler/__init__.py`:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings

scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)

def setup_scheduler():
    """Register all scheduled jobs. Called on FastAPI startup."""
    
    from app.scheduler.morning_jobs import run_morning_jobs
    from app.scheduler.publish_checker import check_due_content
    from app.scheduler.engagement_puller import pull_all_engagement
    from app.scheduler.bc_sync import sync_bc_products
    
    # 6:00 AM daily — BC sync + engagement pull + evaluation trigger
    scheduler.add_job(
        run_morning_jobs,
        CronTrigger(hour=settings.MORNING_SCHEDULE_HOUR, 
                    minute=settings.MORNING_SCHEDULE_MINUTE),
        id="morning_jobs",
        name="Morning: BC sync + engagement + evaluation",
        replace_existing=True,
    )
    
    # Every 15 minutes — check for content due to publish
    scheduler.add_job(
        check_due_content,
        IntervalTrigger(minutes=settings.PUBLISH_CHECK_INTERVAL_MINUTES),
        id="publish_checker",
        name="Check due content for publishing",
        replace_existing=True,
    )
    
    # Every 6 hours — pull engagement metrics
    scheduler.add_job(
        pull_all_engagement,
        IntervalTrigger(hours=settings.ENGAGEMENT_PULL_INTERVAL_HOURS),
        id="engagement_puller",
        name="Pull engagement from social platforms",
        replace_existing=True,
    )
    
    # Every 6 hours — sync BC products
    scheduler.add_job(
        sync_bc_products,
        IntervalTrigger(hours=settings.BC_SYNC_INTERVAL_HOURS),
        id="bc_sync",
        name="Sync Business Central products",
        replace_existing=True,
    )
    
    scheduler.start()
```

In `backend/app/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.scheduler import setup_scheduler, scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_scheduler()
    yield
    scheduler.shutdown()

app = FastAPI(title="MARKAI API", lifespan=lifespan)
```

### 1.6 Publish Checker (Previously n8n Workflow 6)

`backend/app/scheduler/publish_checker.py`:

```python
async def check_due_content():
    """
    Every 15 minutes: query PostgreSQL for content with status='scheduled' 
    and scheduled_at <= now. For each, dispatch to the n8n publish webhook 
    for the correct platform.
    """
    async with get_db_session() as db:
        due_items = await db.execute(
            select(Content)
            .join(CalendarItem)
            .where(Content.status == "scheduled")
            .where(CalendarItem.scheduled_at <= func.now())
        )
        
        for content in due_items.scalars():
            calendar_item = content.calendar_item
            brand = content.brand
            
            # Build payload for n8n
            payload = {
                "content_id": str(content.id),
                "channel": calendar_item.channel,
                "caption": content.platform_adaptations.get(
                    calendar_item.channel, {"caption": content.caption}
                ).get("caption", content.caption),
                "image_url": content.generated_image_url or content.product_image_url,
                "hashtags": content.hashtags,
                # Platform-specific credentials from brand settings
                **get_platform_credentials(brand, calendar_item.channel),
            }
            
            # Dispatch to n8n webhook for the specific platform
            n8n_webhook = f"{settings.N8N_WEBHOOK_BASE}/markai/publish/{calendar_item.channel}"
            
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(n8n_webhook, json=payload)
                    resp.raise_for_status()
                    
                content.status = "publishing"
                await db.commit()
                
                log_scheduled_job("publish_dispatch", "completed", 
                                  {"content_id": str(content.id), "channel": calendar_item.channel})
            except Exception as e:
                log_scheduled_job("publish_dispatch", "failed",
                                  {"content_id": str(content.id), "error": str(e)})
                await notify_failure("publish_dispatch", content, e)
```

### 1.7 Engagement Puller (Previously n8n Workflow 5)

`backend/app/scheduler/engagement_puller.py`:

```python
async def pull_all_engagement():
    """
    Pull engagement metrics directly from social platform APIs.
    No n8n needed — just HTTP calls.
    """
    async with get_db_session() as db:
        # Get all published content from the last 30 days
        recent_published = await db.execute(
            select(Content)
            .where(Content.status == "published")
            .where(Content.published_at >= func.now() - timedelta(days=30))
            .where(Content.platform_post_id.isnot(None))
        )
        
        for content in recent_published.scalars():
            channel = content.calendar_item.channel
            try:
                if channel == "instagram":
                    metrics = await pull_instagram_insights(content)
                elif channel == "facebook":
                    metrics = await pull_facebook_insights(content)
                elif channel == "linkedin":
                    metrics = await pull_linkedin_insights(content)
                else:
                    continue
                
                # Upsert engagement record
                await upsert_engagement(db, content.id, channel, metrics)
                
            except Exception as e:
                logger.warning(f"Engagement pull failed for {content.id}: {e}")


async def pull_instagram_insights(content: Content) -> dict:
    """Direct call to Instagram Graph API — no n8n middleman."""
    brand = content.brand
    token = brand.social_credentials.get("meta_access_token")
    post_id = content.platform_post_id
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://graph.facebook.com/v21.0/{post_id}/insights",
            params={
                "metric": "impressions,reach,saved,likes,comments,shares",
                "access_token": token,
            }
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    
    metrics = {}
    for m in data:
        metrics[m["name"]] = m.get("values", [{}])[0].get("value", 0)
    
    return {
        "impressions": metrics.get("impressions", 0),
        "reach": metrics.get("reach", 0),
        "saves": metrics.get("saved", 0),
        "likes": metrics.get("likes", 0),
        "comments": metrics.get("comments", 0),
        "shares": metrics.get("shares", 0),
    }

# Similar functions for pull_facebook_insights() and pull_linkedin_insights()
```

### 1.8 Notification Service (Previously n8n Error Handler)

`backend/app/services/notification_service.py`:

```python
async def notify_failure(job_name: str, entity: Any, error: Exception):
    """
    Send failure alerts to Slack and create in-app notifications.
    Replaces n8n error handler workflow.
    """
    # Slack
    if settings.SLACK_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(settings.SLACK_WEBHOOK_URL, json={
                    "text": f"🚨 MARKAI {job_name} failed: {str(error)}"
                })
        except Exception:
            logger.error("Slack notification failed")
    
    # In-app notification for all admins
    async with get_db_session() as db:
        admins = await db.execute(
            select(User).where(User.role.in_(["super_admin", "brand_manager"]))
        )
        for admin in admins.scalars():
            await create_notification(db, admin.id, "system_failure",
                f"Job '{job_name}' failed", str(error))
    
    # Email (optional)
    if settings.SMTP_HOST:
        await send_email_alert(job_name, entity, error)
```

---

## Phase 2: Auth & Brand Layer (Week 3-4)

### 2.1 Entra ID Auth — Backend

Implement JWT validation in FastAPI:
- Validate tokens from Entra ID using `python-jose` and JWKS endpoint
- Extract user claims (oid, email, name, roles)
- Auto-create user record on first login
- RBAC middleware checking `user.role` against endpoint permissions

### 2.2 Entra ID Auth — Frontend

Use NextAuth.js with Azure AD provider. Pass access_token to FastAPI in Authorization header.

### 2.3 Brand CRUD

Full brand management API and portal UI. The brand form includes a **Social Credentials** tab where platform tokens and IDs are stored per brand (used by both the publish dispatcher and engagement puller).

### 2.4 Fabric Lakehouse Integration

The Fabric service authenticates with the separate Entra ID app (client_credentials flow) and queries `lh_bronze` via Power BI REST API executeQueries endpoint using DAX queries.

**Key queries:**
- Recently added items: `WHERE [Created_Date] >= DATE_ADD(TODAY(), -30, DAY)`
- Expiring soon items: `WHERE [Expiry_Date] <= DATE_ADD(TODAY(), 60, DAY) AND [Expiry_Date] >= TODAY()`
- All active items for brand mapping: vendor-based filtering

**Product sync** runs every 6 hours via APScheduler, flags `is_new` and `is_expiring_soon`, matches to brands, and emits `product.sync.completed` to NATS.

---

## Phase 3: Research & Strategy Workflows (Week 5-7)

### 3.1 Product Intelligence Workflow

**LangGraph graph: `product_intel`**

Nodes:
1. `discover_brands` — Group unmapped products by vendor, find actual brand
2. `research_brand` — Find website, socials, extract brand colors (Playwright), find product images
3. `match_products_to_brands` — Associate products with brands, suggest new brand creation
4. `source_product_images` — Priority: BC picture → supplier website → web search. **NEVER AI-generate.**
5. `flag_promotable` — New arrivals, expiring stock, seasonal items, high-margin items

### 3.2 Research Workflow

**LangGraph graph: `research`** — Crawl website, analyze social, analyze competitors, identify gaps, build personas, store results.

### 3.3 Strategy Workflow

**LangGraph graph: `strategy`** — Generate positioning, pillars, audiences, cadence, themes. **Always** pauses at `interrupt()` for human approval.

---

## Phase 4: Content Engine (Week 8-10)

### 4.1 Calendar Planning Workflow

**LangGraph graph: `planning`** — Generate campaign calendar, weekly schedule, assign products, define asset needs.

### 4.2 Content Generation Workflow

**LangGraph graph: `content_generation`** — Generate hook, caption, hashtags, CTA, source product image, generate AI background, adapt per platform.

### 4.3 Image Sourcing Pipeline (CRITICAL)

```python
async def source_product_image(product: Product) -> ProductImage:
    """
    Find a REAL product image. Never AI-generate.
    Priority: Business Central → Supplier website → Web search
    """
    # Step 1: Check BC item pictures table via Fabric
    bc_image = await check_bc_product_image(product.bc_item_no)
    if bc_image:
        stored = await store_in_minio(bc_image, f"products/{product.bc_item_no}")
        return ProductImage(url=stored, source="bc")
    
    # Step 2: Search supplier website
    if product.vendor_name:
        supplier_image = await search_supplier_website(product.vendor_name, product.name)
        if supplier_image:
            stored = await store_in_minio(supplier_image, f"products/{product.bc_item_no}")
            return ProductImage(url=stored, source="supplier")
    
    # Step 3: Web search
    web_image = await web_search_product_image(f"{product.vendor_name} {product.name}")
    if web_image:
        stored = await store_in_minio(web_image, f"products/{product.bc_item_no}")
        return ProductImage(url=stored, source="websearch")
    
    return ProductImage(url=None, source="none", needs_manual=True)
```

### 4.4 Content Studio UI

Kanban board, content editor, asset preview, bulk actions, product linkage, calendar view with drag-and-drop.

---

## Phase 5: Approval & Publishing (Week 11-12)

### 5.1 Approval State Machine

```
planned → generating → draft → internal_review → client_review → approved → scheduled → publishing → published → archived
                                     ↓                  ↓
                                  rejected           rejected → regenerating (with feedback)
```

### 5.2 Publishing Flow

1. Content reaches `approved` → user or auto-scheduler sets to `scheduled`
2. APScheduler `publish_checker` runs every 15 minutes
3. Finds content where `scheduled_at <= now`
4. Builds payload with platform-specific formatting
5. POSTs to n8n webhook for the correct platform (`/markai/publish/instagram`, etc.)
6. n8n makes the social API call and calls back to `POST /api/v1/webhooks/publish-result`
7. FastAPI updates content status to `published` with `platform_post_id`

**n8n only touches the social platform API call.** Everything before and after is FastAPI.

### 5.3 Engagement Collection

APScheduler `engagement_puller` runs every 6 hours. Directly calls Instagram/Facebook/LinkedIn APIs using tokens from `brands.social_credentials`. Stores results in `engagement_metrics`. No n8n involved.

---

## Phase 6: Evaluation & Self-Improvement (Week 13-15)

### 6.1 Evaluation Workflow

**LangGraph graph: `evaluation`** — Triggered by morning job. Analyzes performance, generates recommendations with confidence scores, classifies into three adaptation tiers.

### 6.2 Promptfoo Integration

Regression testing on every prompt change. Quality gates at 90% pass rate. CI/CD compatible.

---

## Phase 7: Observability & Polish (Week 16-17)

### 7.1 Grafana Dashboards

Three pre-provisioned dashboards: MARKAI Overview, Agent Workflows, Content Pipeline.

### 7.2 Scheduler Monitoring

The `scheduled_job_log` table tracks every APScheduler execution. The System Operations page in the portal shows:
- Last run time for each job
- Success/failure count per job
- Failed job details with error messages
- Manual trigger buttons (re-run any job on demand)

### 7.3 Alerting

Prometheus rules for: service down, workflow failure rate, publishing failure, NATS queue depth, scheduler job failures.

---

## Phase 8: Final Integration & Testing (Week 18)

- End-to-end test: Create brand → research → strategy → plan → generate → approve → publish
- BC sync test: Verify product discovery, image sourcing, promotion flagging
- Scheduler test: Verify all APScheduler jobs fire correctly
- n8n test: Verify social publishing for each platform
- Security audit: Entra ID auth on all endpoints, RBAC enforcement
- Load test: 10 brands, 50 content items each
- Seed production data: Import existing Chemtech brands

---

## Key Implementation Notes

### What Lives Where

| Responsibility | Lives In | NOT In |
|---------------|----------|--------|
| Scheduling (cron, intervals) | FastAPI APScheduler | ~~n8n~~ |
| Engagement data pulling | FastAPI engagement_puller | ~~n8n~~ |
| Error/failure notifications | FastAPI notification_service | ~~n8n~~ |
| Publish due-content checks | FastAPI publish_checker | ~~n8n~~ |
| Social platform API publish calls | n8n (3 webhooks) | ~~FastAPI~~ |
| AI reasoning / content generation | LangGraph agents | ~~n8n~~ |
| All data storage decisions | FastAPI services | ~~n8n~~ |

### Product Image Rule (CRITICAL)
```
RULE: Content images must use REAL product photos.
- AI generation is ONLY allowed for backgrounds, scenes, and decorative elements.
- The product itself must be a real photograph.
- Source priority: Business Central → Supplier website → Web search
- If no real image found: flag for manual resolution, do NOT generate.
```

### LiteLLM Usage Pattern
```python
# ALWAYS use LiteLLM, never import openai directly
from litellm import completion, embedding

response = completion(
    model="markai-text",
    messages=[{"role": "user", "content": prompt}],
    api_base=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_MASTER_KEY,
)
```

### n8n Webhook Contract

FastAPI dispatches publish jobs to n8n via POST. n8n calls back with results.

**Outbound (FastAPI → n8n):**
```json
POST {N8N_WEBHOOK_BASE}/markai/publish/{platform}
{
    "content_id": "uuid",
    "caption": "string",
    "image_url": "https://...",
    "hashtags": ["string"],
    "access_token": "string",
    "page_id": "string",          // facebook
    "instagram_account_id": "string", // instagram
    "org_id": "string"            // linkedin
}
```

**Inbound (n8n → FastAPI):**
```json
POST /api/v1/webhooks/publish-result
{
    "content_id": "uuid",
    "platform": "instagram",
    "status": "published" | "failed",
    "platform_post_id": "string",
    "published_at": "iso-timestamp",
    "error": "string"             // only if failed
}
```
