# MARKAI PROJECT AUDIT PROMPT

> **For the auditing agent:** This document contains everything you need to perform a comprehensive audit of the MARKAI codebase. Every file path, dependency version, endpoint, and pattern referenced below was extracted directly from the actual source code on 2026-04-01. Execute each section methodically.

---

## 1. PROJECT CONTEXT BRIEFING

**MARKAI** is an autonomous AI marketing operating system built for a Mauritius-based company. It ingests brand data (including product catalogs from Microsoft Business Central via Microsoft Fabric), researches the competitive landscape, generates a content strategy, plans a content calendar, and then autonomously produces publication-ready social media content complete with AI-generated images, branded overlays, platform-specific mockups, and multi-channel adaptations. Human marketers approve or reject content via a kanban-style approval workflow before posts are published to social platforms through n8n webhook automations.

**Architecture:** MARKAI is a microservices system orchestrated via Docker Compose with 15+ containers. The core services are: (1) a **FastAPI backend** (`backend/`) that exposes a REST API, manages the PostgreSQL database, runs APScheduler cron jobs, and publishes NATS messages; (2) a **LangGraph agents worker** (`agents/`) that subscribes to NATS JetStream subjects and runs 7 AI workflow graphs (research, strategy, planning, content, evaluation, adaptation, product_intel); (3) a **Next.js 16 frontend** (`frontend/`) with React 19, shadcn/ui components, and Azure AD SSO via NextAuth; (4) a **browser worker** (`browser-worker/`) running Playwright for web scraping and screenshot capture; (5) a **notifications service** (`notifications/`) providing SSE-based real-time notifications and Teams webhook integration; (6) **LiteLLM** as an LLM gateway proxying requests to OpenAI (GPT-5.4, GPT-5.4-mini, gpt-image-1.5, dall-e-3) and Google Gemini (gemini-2.5-flash/pro); (7) supporting infrastructure including PostgreSQL 16, Qdrant v1.17 (vector DB), MinIO (object storage), NATS 2.12.5 (message broker), Valkey 9.0.3 (Redis-compatible cache), n8n 1.82.1 (social publishing workflows), and a full observability stack (Grafana 12.4.1, Prometheus v3.10, Loki 3.6.7, OpenTelemetry Collector 0.147).

**Tech Stack:** Python 3.13 (backend, agents, browser-worker, notifications), Node.js 22 (frontend), PostgreSQL 16, Traefik v3.6 reverse proxy. All Python services use Hatchling/setuptools build systems. The frontend uses npm with package-lock.json.

**Deployment:** VPS production deployment uses a shared Traefik reverse proxy on an external `n8n_default` network. The `docker-compose.vps.yml` overlay disables the bundled Traefik, connects frontend/backend to the external network, and adds Traefik labels for auto-discovery. Domain: `MARKAI_DOMAIN` env var (e.g., `markai.srv1191974.hstgr.cloud`).

**Maturity:** Growing product — past the prototype stage with a working end-to-end pipeline, comprehensive database schema, multiple audit rounds completed (see `AUDIT_ARTIFACTS/`), but still single-developer patterns, limited test coverage, and some areas of technical debt (duplicate content fixes, French text in old data, image generation model compatibility issues).

**What works well:** The LangGraph workflow architecture is clean and modular — each workflow has its own `graph.py`, `nodes.py`, and `state.py`. The database schema is well-normalized with proper foreign keys, indexes, and constraints. The NATS-based message passing with durable consumers provides reliable workflow chaining. The brand onboarding flow (onboarding → activating → active) is well-structured. Configuration management via Pydantic Settings with production-time validation is solid.

**Known debt:** The `worker.py` file at 878 lines contains complex chaining logic that is difficult to follow. The intelligence endpoint at `backend/app/api/v1/intelligence.py` contains inline LLM calling logic that duplicates `agents/shared/llm.py`. Some API endpoints use raw SQL via `text()` instead of the ORM. The notification SSE endpoint polls every 10 seconds instead of using pub/sub.

---

## 2. TECH STACK & DEPENDENCY MANIFEST

### Backend (Python 3.13) — `backend/pyproject.toml`

| Dependency | Version | Purpose in MARKAI |
|---|---|---|
| `fastapi[standard]` | >=0.135 | REST API framework — all `/api/v1/*` endpoints |
| `uvicorn[standard]` | latest | ASGI server — runs via `app.main:app` |
| `sqlalchemy[asyncio]` | >=2.0.48 | Async ORM — models in `backend/app/models/`, sessions via `async_session_factory` |
| `asyncpg` | >=0.31 | PostgreSQL async driver — used by SQLAlchemy engine |
| `alembic` | >=1.18 | Database migrations — config at `backend/alembic.ini` |
| `pydantic` | >=2.12 | Request/response schemas in `backend/app/schemas/` |
| `pydantic-settings` | >=2.13 | Configuration management — `backend/app/config.py` Settings class |
| `PyJWT[crypto]` | latest | Azure AD JWT validation — `backend/app/auth/entra.py` |
| `httpx` | >=0.28 | Async HTTP client — Microsoft Graph API calls, LiteLLM proxy, product image search |
| `pyodbc` | >=5.3 | ODBC driver — Microsoft Fabric SQL endpoint queries |
| `apscheduler` | >=3.11 | Scheduled jobs — `backend/app/scheduler/` (morning jobs, publish checker, BC sync, engagement puller, model discovery) |
| `nats-py` | >=2.14 | NATS JetStream client — `backend/app/services/nats_service.py` |
| `minio` | >=7.2 | MinIO S3-compatible client — `backend/app/services/minio_service.py` |
| `qdrant-client` | >=1.17 | Vector DB client — `backend/app/services/qdrant_service.py` |
| `litellm` | >=1.60 | LLM abstraction — `backend/app/services/ai_model_service.py` model discovery |
| `redis` | >=7.1 | Valkey/Redis client — caching in `ai_model_service.py`, health checks |
| `python-multipart` | >=0.0.18 | File upload handling — brand logos, product images |
| `google-genai` | >=1.5 | Google Gemini API — `backend/app/services/gemini_service.py` product image replacement |
| `Pillow` | >=12.0 | Image processing — Gemini service image handling |
| `bcrypt` | >=4.0 | Password hashing (imported but not actively used — Azure AD handles auth) |
| `opentelemetry-api` | >=1.40 | Distributed tracing — `backend/app/main.py` telemetry setup |
| `opentelemetry-sdk` | >=1.40 | Tracing SDK — span processor with OTLP exporter |
| `opentelemetry-instrumentation-fastapi` | >=0.61b0 | Auto-instrument FastAPI routes |
| `opentelemetry-exporter-otlp` | >=1.40 | Export traces to OTLP collector |
| `slowapi` | >=0.1.9 | API rate limiting — 120/min default, 5/min on activation, 10/min on AI generation |
| `prometheus-fastapi-instrumentator` | >=7.0 | Prometheus metrics endpoint at `/metrics` |
| `python-json-logger` | >=3.0 | Structured JSON logging for production observability |
| `tenacity` | >=8.2 | Retry logic — LLM calls in `intelligence.py` |

### Agents (Python 3.13) — `agents/pyproject.toml`

| Dependency | Version | Purpose in MARKAI |
|---|---|---|
| `langgraph` | >=1.0,<2.0 | LangGraph workflow framework — all 7 workflow graphs |
| `langchain-core` | >=1.0,<2.0 | LangChain core abstractions |
| `langchain-openai` | >=1.0,<2.0 | OpenAI LangChain integration |
| `litellm` | >=1.60 | LLM proxy client (installed but calls go through httpx to LiteLLM proxy) |
| `nats-py` | >=2.14 | NATS JetStream consumer — `agents/shared/nats_consumer.py` |
| `asyncpg` | >=0.31 | Direct DB access — `agents/shared/tools/database.py` |
| `sqlalchemy[asyncio]` | >=2.0.48 | Async engine for DB operations in agents |
| `httpx` | >=0.28 | LLM API calls via LiteLLM proxy, browser worker calls |
| `pyodbc` | >=5.3 | Fabric SQL queries for product data |
| `minio` | >=7.2 | Object storage for generated images |
| `qdrant-client` | >=1.17 | Vector search for content similarity |
| `playwright` | >=1.58 | Web scraping in research workflow (installed in Docker with Chromium) |
| `pydantic` | >=2.12 | Calendar item validation (`CalendarItemValidator` in planning nodes) |
| `pydantic-settings` | >=2.13 | Agent configuration — `agents/shared/config.py` |
| `google-genai` | >=1.5 | Gemini API for product image operations |
| `Pillow` | >=12.0 | Image processing — logo overlay, mockup generation, SVG rendering |
| `numpy` | >=2.0 | Image analysis — variance calculation for logo placement |
| `tenacity` | >=9.0 | LLM retry logic — `agents/shared/llm.py` |
| `python-json-logger` | >=3.0 | Structured logging |

### Frontend (Node.js 22) — `frontend/package.json`

| Dependency | Version | Purpose in MARKAI |
|---|---|---|
| `next` | ^16.2.1 | Next.js 16 framework — App Router |
| `react` | ^19.2.4 | React 19 UI library |
| `react-dom` | ^19.2.4 | React DOM renderer |
| `next-auth` | ^4.24.11 | Azure AD SSO authentication — `frontend/src/lib/auth.ts` |
| `@auth/core` | ^0.37.4 | Auth.js core library |
| `zustand` | ^5.0.3 | State management — `frontend/src/stores/brand-store.ts` |
| `@dnd-kit/core` | ^6.3.1 | Drag and drop — kanban board |
| `@dnd-kit/sortable` | ^10.0.0 | Sortable drag and drop |
| `@dnd-kit/utilities` | ^3.2.2 | DnD utilities |
| `@radix-ui/react-avatar` | ^1.1.2 | shadcn/ui avatar component |
| `@radix-ui/react-dialog` | ^1.1.4 | shadcn/ui dialog component |
| `@radix-ui/react-dropdown-menu` | ^2.1.4 | shadcn/ui dropdown menu |
| `@radix-ui/react-label` | ^2.1.1 | shadcn/ui label |
| `@radix-ui/react-select` | ^2.1.4 | shadcn/ui select |
| `@radix-ui/react-separator` | ^1.1.1 | shadcn/ui separator |
| `@radix-ui/react-slot` | ^1.1.1 | shadcn/ui slot |
| `@radix-ui/react-switch` | ^1.2.6 | shadcn/ui switch toggle |
| `@radix-ui/react-tabs` | ^1.1.2 | shadcn/ui tabs |
| `@radix-ui/react-tooltip` | ^1.1.6 | shadcn/ui tooltip |
| `class-variance-authority` | ^0.7.1 | Component variant management (shadcn/ui) |
| `clsx` | ^2.1.1 | Conditional class names |
| `date-fns` | ^4.1.0 | Date formatting — calendar views |
| `lucide-react` | ^0.468.0 | Icon library |
| `next-themes` | ^0.4.4 | Dark/light theme support |
| `postcss` | ^8.4.49 | CSS processing |
| `react-markdown` | ^10.1.0 | Markdown rendering — intelligence reports |
| `recharts` | ^3.8.1 | Charts — engagement analytics, performance grids |
| `sonner` | ^2.0.7 | Toast notifications |
| `tailwind-merge` | ^2.6.0 | Tailwind class merging |

**Dev Dependencies:**
| `tailwindcss` | ^4.2.2 | Tailwind CSS 4 |
| `@tailwindcss/postcss` | ^4.2.2 | Tailwind PostCSS plugin |
| `typescript` | ^5.7.2 | TypeScript compiler |
| `@types/node` | ^25.5.0 | Node.js type definitions |
| `@types/react` | ^19.2.14 | React type definitions |
| `@types/react-dom` | ^19.2.3 | React DOM type definitions |
| `eslint` | ^9.17.0 | Linter |
| `eslint-config-next` | ^16.2.1 | Next.js ESLint config |

### Browser Worker (Python 3.13) — `browser-worker/pyproject.toml`

| Dependency | Version | Purpose |
|---|---|---|
| `fastapi[standard]` | >=0.135 | HTTP API for capture/scrape endpoints |
| `playwright` | >=1.58 | Headless Chromium for web scraping |
| `beautifulsoup4` | >=4.14 | HTML parsing for social scraping |
| `minio` | >=7.2 | Upload captured screenshots to object storage |
| `Pillow` | >=12.1 | Image processing |

### Notifications Service (Python 3.13) — `notifications/pyproject.toml`

| Dependency | Version | Purpose |
|---|---|---|
| `fastapi[standard]` | >=0.135 | HTTP API + SSE endpoint |
| `sse-starlette` | >=3.3 | Server-Sent Events for real-time notifications |
| `valkey` | >=6.1 | Valkey pub/sub for notification distribution |
| `asyncpg` | >=0.31 | Direct DB access for notification queries |
| `sqlalchemy[asyncio]` | >=2.0.48 | ORM for notification records |

### Infrastructure Images (from docker-compose.yml)

| Service | Image | Version |
|---|---|---|
| Traefik | `traefik` | v3.6 |
| PostgreSQL | `postgres` | 16-alpine |
| Qdrant | `qdrant/qdrant` | v1.17.0 |
| MinIO | `minio/minio` | RELEASE.2025-01-20T14-49-07Z |
| Valkey | `valkey/valkey` | 9.0.3-alpine |
| NATS | `nats` | 2.12.5-alpine |
| LiteLLM | `ghcr.io/berriai/litellm` | v1.82.3-stable.patch.2 |
| n8n | `docker.n8n.io/n8nio/n8n` | 1.82.1 |
| Grafana | `grafana/grafana` | 12.4.1 |
| Prometheus | `prom/prometheus` | v3.10.0 |
| Loki | `grafana/loki` | 3.6.7 |
| Promtail | `grafana/promtail` | 3.6.7 |
| OTel Collector | `otel/opentelemetry-collector-contrib` | 0.147.0 |

---

## 3. ARCHITECTURE MAP

### Directory Structure

```
D:\MarkAI\
├── agents/                          # LangGraph AI workflow workers
│   ├── Dockerfile                   # Python 3.13, Playwright Chromium, ImageMagick
│   ├── pyproject.toml               # Dependencies: langgraph, langchain, litellm, nats-py
│   ├── worker.py                    # MAIN ENTRY POINT: NATS consumer, graph dispatch, workflow chaining (878 lines)
│   ├── shared/
│   │   ├── config.py                # Pydantic Settings for agents (env vars)
│   │   ├── llm.py                   # LiteLLM proxy wrapper: chat_completion, get_embedding, generate_image
│   │   ├── nats_consumer.py         # NATS JetStream durable push consumer
│   │   ├── sanitize.py              # Prompt injection prevention (9 patterns)
│   │   ├── state.py                 # BaseState TypedDict
│   │   ├── image_processing.py      # Logo overlay, mockup generation (Instagram/Facebook/LinkedIn/X)
│   │   └── tools/
│   │       ├── database.py          # Async SQLAlchemy DB operations (agent_runs, brands, calendar, content)
│   │       ├── storage.py           # MinIO upload/download helpers
│   │       ├── vector.py            # Qdrant vector operations
│   │       ├── browser.py           # Playwright web scraping via browser-worker
│   │       ├── web_search.py        # Web search utilities
│   │       ├── image_search.py      # Product image search
│   │       ├── social.py            # Social media API helpers
│   │       └── fabric.py            # Microsoft Fabric SQL queries
│   ├── workflows/
│   │   ├── research/                # Brand research: crawl_website → analyze_social → analyze_competitors → identify_gaps → build_personas → store_results
│   │   ├── strategy/                # Strategy: load_research → generate_positioning → define_pillars → define_audiences → plan_cadence → generate_themes → human_review
│   │   ├── planning/                # Calendar: load_strategy → generate_campaigns → generate_calendar → assign_products → store_calendar
│   │   ├── content/                 # Content: load_context → generate_hook → generate_caption → generate_hashtags → source_product_image → generate_background → apply_branding → adapt_platforms → generate_mockups → store_content
│   │   ├── evaluation/              # Eval: load_performance → analyze_patterns → generate_recommendations → classify_adaptations → store_adaptations
│   │   ├── adaptation/              # Adapt: load_adaptations → apply_tier1 → propose_tier2 → propose_tier3
│   │   └── product_intel/           # Intel: discover_brands → research_brand → match_products → source_images → flag_promotable
│   └── tests/
│       ├── test_llm_parsing.py
│       └── test_sanitize.py
│
├── backend/                         # FastAPI REST API
│   ├── Dockerfile                   # Python 3.13, MSSQL ODBC driver, non-root user
│   ├── pyproject.toml
│   ├── alembic.ini                  # Alembic migration config
│   ├── alembic/env.py               # Migration environment
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, rate limiting, OTel, Prometheus, health check, global exception handler
│   │   ├── config.py                # Pydantic Settings (60+ env vars), production startup validation
│   │   ├── deps.py                  # get_db, get_current_user (Azure AD JWT → User record)
│   │   ├── auth/
│   │   │   ├── entra.py             # Azure AD JWT validation, Graph API (user search, group checks, token caching)
│   │   │   ├── models.py            # User, Notification, AuditLog, ScheduledJobLog ORM models
│   │   │   └── permissions.py       # Role hierarchy: admin(100) > manager(80) > editor(60) > viewer(10)
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   │   ├── base.py              # Engine (pool_size=20, max_overflow=10), DeclarativeBase
│   │   │   ├── brand.py             # Brand model with ALL_CHANNELS, CHANNEL_DISPLAY_NAMES
│   │   │   ├── calendar_item.py     # CalendarItem model
│   │   │   ├── content.py           # Content model with is_current partial unique index
│   │   │   ├── campaign.py          # Campaign model
│   │   │   ├── approval.py          # Approval model
│   │   │   ├── agent_run.py         # AgentRun model with running unique constraint
│   │   │   ├── product.py           # Product model (BC sync)
│   │   │   ├── competitor.py        # Competitor model
│   │   │   ├── engagement.py        # EngagementMetrics model
│   │   │   ├── adaptation.py        # Adaptation model (multi-channel variants)
│   │   │   ├── ai_model.py          # AIModel, AIModelCategory, AIModelSelection
│   │   │   └── prompt_version.py    # PromptVersion model (A/B testing)
│   │   ├── schemas/                 # Pydantic request/response schemas (mirrors models)
│   │   ├── services/                # Business logic layer
│   │   │   ├── brand_service.py     # Brand CRUD
│   │   │   ├── content_service.py   # Content CRUD + status transitions (InvalidStatusTransition)
│   │   │   ├── calendar_service.py  # Calendar CRUD + reorder
│   │   │   ├── approval_service.py  # Approval workflow (resolve → update calendar_item status)
│   │   │   ├── product_service.py   # Product CRUD + BC upsert
│   │   │   ├── prompt_service.py    # Prompt versioning + A/B selection
│   │   │   ├── nats_service.py      # NATS JetStream publish + stream management
│   │   │   ├── minio_service.py     # MinIO upload/download/presigned URLs
│   │   │   ├── qdrant_service.py    # Qdrant vector operations
│   │   │   ├── fabric_service.py    # Microsoft Fabric SQL (BC companies, locations, stock)
│   │   │   ├── gemini_service.py    # DuckDuckGo image search + Gemini product replacement
│   │   │   ├── ai_model_service.py  # Model discovery, active model selection, Valkey caching
│   │   │   ├── analytics_service.py
│   │   │   ├── engagement_service.py
│   │   │   ├── notification_service.py
│   │   │   ├── publish_service.py
│   │   │   └── content_service.py
│   │   ├── api/
│   │   │   ├── router.py            # Main router: mounts all 19 v1 sub-routers + audit alias
│   │   │   └── v1/                  # 19 endpoint modules (see Section 9)
│   │   └── scheduler/
│   │       ├── __init__.py          # APScheduler setup: 5 jobs (morning, publish check, engagement, BC sync, model discovery)
│   │       ├── morning_jobs.py      # Daily: BC sync + engagement pull + evaluation trigger
│   │       ├── publish_checker.py   # Every 15min: check due content → trigger n8n publish
│   │       ├── engagement_puller.py # Every 6h: pull metrics from social APIs
│   │       ├── bc_sync.py           # Every 6h: sync Business Central products via Fabric
│   │       └── model_discovery.py   # Daily 3AM: discover available AI models from OpenAI
│   └── tests/
│       ├── conftest.py              # Test fixtures (MARKAI_ENV=test, mock secrets)
│       ├── test_api_health.py
│       ├── test_auth_permissions.py
│       └── test_utils.py
│
├── frontend/                        # Next.js 16 / React 19
│   ├── Dockerfile                   # Multi-stage: deps → builder → runner (node:22-alpine)
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── app/                     # Next.js App Router pages
│       │   ├── page.tsx             # Dashboard (home)
│       │   ├── layout.tsx           # Root layout with Providers wrapper
│       │   ├── providers-wrapper.tsx # SessionProvider + ThemeProvider + Toaster
│       │   ├── auth/signin/page.tsx # Azure AD sign-in page
│       │   ├── brands/             # Brand list, detail ([id]), new brand
│       │   ├── content/            # Content list, detail ([id]), calendar, stage/[status]
│       │   ├── approvals/page.tsx  # Approval workflow
│       │   ├── analytics/page.tsx  # Analytics dashboard
│       │   ├── intelligence/       # Reports list, report detail, products
│       │   ├── learning/page.tsx   # Adaptations/learning
│       │   ├── prompts/page.tsx    # Prompt version management
│       │   ├── providers/page.tsx  # AI model provider management
│       │   ├── settings/           # App settings, user management
│       │   ├── system/             # System health, scheduler, audit log
│       │   └── api/auth/[...nextauth]/route.ts # NextAuth API route
│       ├── components/
│       │   ├── layout/             # Header, Sidebar, BrandSwitcher
│       │   ├── brand/              # BrandCard, BrandForm, BrandOnboarding, CompetitorTracker, tabs/*
│       │   ├── content/            # ContentCard, ContentEditor, KanbanBoard, CalendarView, ChannelPreview, PlatformMockups, AssetPreview
│       │   ├── analytics/          # EngagementChart, PerformanceGrid, PostingHeatmap
│       │   ├── approval/           # ApprovalActions, ApprovalHistory
│       │   ├── system/             # ServiceHealth, QueueDepth, WorkflowMonitor
│       │   └── ui/                 # shadcn/ui primitives (button, card, dialog, select, tabs, etc.)
│       ├── lib/
│       │   ├── auth.ts             # NextAuth config: Azure AD provider, JWT refresh, role caching
│       │   ├── api.ts              # API client: auto-auth, 401 redirect, file proxy helpers
│       │   ├── hooks.ts            # Custom React hooks
│       │   └── utils.ts            # Utility functions (cn, formatters)
│       ├── stores/
│       │   └── brand-store.ts      # Zustand store for active brand selection
│       └── types/
│           ├── index.ts            # All TypeScript interfaces (Brand, Content, CalendarItem, etc.)
│           └── next-auth.d.ts      # NextAuth type augmentations
│
├── browser-worker/                  # Playwright scraping service
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py                 # FastAPI app with /health endpoint
│   │   ├── capture.py              # Screenshot/page capture
│   │   ├── product_image.py        # Product image search via browser
│   │   ├── social_scraper.py       # Social media profile scraping
│   │   └── config.py
│   └── pyproject.toml
│
├── notifications/                   # Real-time notification service
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py                 # FastAPI + SSE streaming
│   │   ├── portal.py               # In-app notification portal
│   │   ├── teams.py                # Microsoft Teams webhook integration
│   │   └── config.py
│   └── pyproject.toml
│
├── db/
│   └── init.sql                    # Full PostgreSQL schema (16 tables, see Section 8)
│
├── litellm/
│   └── config.yaml                 # LiteLLM proxy config: 15 models (OpenAI + Gemini), Valkey cache, 120s timeout
│
├── observability/                   # Monitoring stack configs
│   ├── grafana/                    # Grafana dashboards + datasource provisioning
│   ├── prometheus/                 # Prometheus config + alert rules
│   ├── loki/                       # Loki log aggregation config
│   ├── promtail/                   # Promtail log shipper config
│   └── otel-collector/             # OpenTelemetry Collector config
│
├── traefik/                        # Traefik reverse proxy config
│   ├── traefik.yml                 # Entrypoints, providers
│   └── dynamic/security-headers.yml # Security headers middleware
│
├── scripts/                        # Development/utility scripts
│   ├── seed-dev.py                 # Seed development data
│   ├── bc-table-discovery.py       # Discover Business Central table names
│   └── column-discovery.py         # Discover BC table columns
│
├── eval/                           # Prompt evaluation (promptfoo)
│   ├── promptfooconfig.yaml
│   └── prompts/                    # content_generation.txt, research_summary.txt
│
├── docker-compose.yml              # Base: 15+ services, no host ports (added by overlay)
├── docker-compose.override.yml     # Local dev: host port bindings, hot reload volumes
├── docker-compose.vps.yml          # VPS production: shared Traefik, n8n disabled, observability optional
├── .env.example                    # 50+ environment variables documented
├── .env.vps.example                # VPS-specific env template
└── .github/workflows/ci.yml       # CI: backend lint+test, agents test, frontend lint+typecheck
```

### Request Flow Examples

**1. Brand Activation Pipeline (POST `/api/v1/brands/{id}/activate`)**
```
Frontend → Backend API (brands.py:activate_content_factory)
  → Sets brand.status = "activating"
  → Publishes NATS "research.trigger" message
  → Worker (worker.py) receives on "research.>" subscription
  → Dispatches to research_graph.ainvoke()
  → research_graph: crawl_website → analyze_social → analyze_competitors → identify_gaps → build_personas → store_results
  → Worker chains: publishes "strategy.trigger"
  → strategy_graph: load_research → generate_positioning → define_pillars → define_audiences → plan_cadence → generate_themes → human_review
  → Worker chains: publishes "planning.trigger"
  → planning_graph: load_strategy → generate_campaigns → generate_calendar → assign_products → store_calendar
  → Worker: sets brand.status = "active", publishes "content.generate" for first queued item
  → content_graph: load_context → generate_hook → generate_caption → generate_hashtags → source_product_image → generate_background → apply_branding → adapt_platforms → generate_mockups → store_content
  → Worker: sequential chaining — publishes next calendar_item_id from remaining_queue
```

**2. Content Approval (PUT `/api/v1/approvals/{id}`)**
```
Frontend (ApprovalActions.tsx) → PUT /api/v1/approvals/{id}
  → Backend: approval_service.resolve_approval()
  → Updates approval.status, decided_at
  → If approved: updates calendar_item.status to "approved"
  → If rejected: updates calendar_item.status to "reworking"
```

**3. Image Regeneration (POST `/api/v1/content/{id}/regenerate-image`)**
```
Frontend → POST /api/v1/content/{id}/regenerate-image
  → Backend publishes NATS "content.regenerate-image"
  → Worker._handle_image_regeneration():
    → Reads content from DB
    → Calls generate_image() (OpenAI API direct, falls back dall-e-3)
    → Uploads to MinIO (content-images/{brand_id}/{item_id}/background.png)
    → Updates content.generation_metadata with new image path
```

**4. Dashboard Load (GET `/api/v1/dashboard/stats`)**
```
Frontend → GET /api/v1/dashboard/stats
  → Backend: dashboard.py checks Valkey cache "markai:dashboard:stats"
  → If cached (5min TTL): return cached JSON
  → If miss: raw SQL aggregation (COUNT brands, content, pending approvals, scheduled, published this week, running agents)
  → Cache result → return
```

**5. File Proxy (GET `/api/v1/files/{path}`)**
```
Frontend <img src="/api/v1/files/content-images/brand-id/item-id/bg.png">
  → Backend files.py: parses bucket from path prefix (content-images, brand-assets, markai-assets)
  → Downloads from MinIO via minio_service.download_file()
  → Returns binary with correct Content-Type header and 1h cache
```

### Integration Points

| System | Integration | Files |
|---|---|---|
| **NATS JetStream** | Message broker for workflow dispatch; 1 stream "WORKFLOWS" with 7+ subject patterns | `backend/app/services/nats_service.py`, `agents/worker.py`, `agents/shared/nats_consumer.py` |
| **LiteLLM** | LLM gateway proxying to OpenAI/Gemini; Valkey cache; 120s timeout | `litellm/config.yaml`, `agents/shared/llm.py` |
| **MinIO** | Object storage for images (content-images, brand logos, product galleries) | `backend/app/services/minio_service.py`, `agents/shared/tools/storage.py` |
| **PostgreSQL** | Primary data store; 16 tables; async via asyncpg | `db/init.sql`, `backend/app/models/base.py`, `agents/shared/tools/database.py` |
| **Qdrant** | Vector DB for content similarity search and embeddings | `backend/app/services/qdrant_service.py`, `agents/shared/tools/vector.py` |
| **Valkey** | Redis-compatible cache for LiteLLM, dashboard stats, analytics, model selections | `backend/app/services/ai_model_service.py`, `litellm/config.yaml` |
| **Azure AD** | SSO authentication; JWT validation; Graph API for user search and group membership | `backend/app/auth/entra.py`, `frontend/src/lib/auth.ts` |
| **Microsoft Fabric** | SQL endpoint for Business Central product data (items, categories, vendors, ledger entries) | `backend/app/services/fabric_service.py`, `agents/shared/tools/fabric.py` |
| **n8n** | Webhook-based social media publishing; receives publish commands from publish_checker | `backend/app/scheduler/publish_checker.py`, `backend/app/api/v1/webhooks.py` |
| **OpenAI API** | Direct calls for image generation (bypasses LiteLLM); model discovery | `agents/shared/llm.py:generate_image()`, `backend/app/scheduler/model_discovery.py` |
| **Google Gemini** | Product image replacement (swap generic product in marketing image with real photo) | `backend/app/services/gemini_service.py` |
| **Microsoft Teams** | Webhook notifications for content approvals and system alerts | `notifications/app/teams.py` |

---

## 4. FILE-BY-FILE AUDIT DIRECTIVES

### HIGH PRIORITY (Core logic, security-critical, highest-churn)

| File | Lines | Audit Focus |
|---|---|---|
| `agents/worker.py` | ~878 | Workflow dispatch, chaining logic, skip-forward, sequential content queuing, error handling, timeout handling, idempotency via IntegrityError, activation state management. **Check:** chain_depth limits, race conditions in skip logic, error recovery paths, message acknowledgment correctness. |
| `agents/shared/llm.py` | ~390 | LLM proxy wrapper, model resolution from backend API, retry logic, image generation with fallback chain. **Check:** timeout scaling formula (`max(120, min(600, max_tokens // 10))`), fallback model cache TTL, error classification in `_is_retryable`, direct OpenAI API key exposure for image generation. |
| `agents/workflows/content/nodes.py` | ~600+ | Content generation pipeline: hook, caption, hashtags, product image sourcing, background generation, branding overlay, platform adaptations, mockup generation, DB storage. **Check:** prompt injection via brand data, image processing error handling, caption length constraints per platform, deduplication context. |
| `agents/workflows/planning/nodes.py` | ~566 | Calendar generation: weekly batch LLM calls, Pydantic validation, deduplication context, product assignment, strategy document generation. **Check:** batch loop correctness, dedup context rebuild, `store_calendar_items` max_date filtering, CalendarItemValidator edge cases. |
| `backend/app/api/v1/brands.py` | ~602 | Brand CRUD, onboarding validation, activation trigger, channel config, logo upload/serve/delete, competitor CRUD. **Check:** `_strip_sensitive_guidelines` completeness, JSONB mutation with `flag_modified`, logo file size/type validation, activation re-entry logic. |
| `frontend/src/lib/auth.ts` | ~149 | NextAuth Azure AD config, JWT refresh, role caching from backend. **Check:** token refresh race conditions, error handling when backend unreachable (defaults to "manager" role), session maxAge (7 days). |
| `frontend/src/lib/api.ts` | ~185 | API client with auto-auth, 401 redirect, URL normalization, file proxy helpers. **Check:** trailing slash logic (complex regex), HTTPS upgrade logic, file URL rewriting for legacy MinIO paths. |

### MEDIUM PRIORITY (Business logic, UI components, services)

| File | Audit Focus |
|---|---|
| `agents/workflows/research/nodes.py` | Web crawling, social analysis, competitor analysis, persona building — check error handling, Playwright timeouts, LLM output parsing |
| `agents/workflows/strategy/nodes.py` | Positioning, pillars, audiences, cadence, themes — check LLM JSON parsing reliability, strategy output structure |
| `agents/workflows/evaluation/nodes.py` | Performance analysis, recommendation generation, adaptation classification — check engagement data handling |
| `agents/workflows/adaptation/nodes.py` | Tier1/2/3 adaptation logic — check tier classification, auto-apply safety |
| `agents/workflows/product_intel/nodes.py` | Brand discovery, product matching, image sourcing — check vendor data handling |
| `agents/shared/image_processing.py` | Logo overlay, mockup generation — check SVG rendering security (subprocess.run), font loading paths, image dimension handling |
| `agents/shared/tools/database.py` | Async DB operations — check SQL injection via `text()`, connection pool management, transaction handling |
| `backend/app/api/v1/intelligence.py` | Intelligence reports, workflow triggers, AI field generation/rewrite — check inline `_call_llm` duplication, rate limiting, sanitization |
| `backend/app/api/v1/content.py` | Content CRUD, image regeneration trigger, status transitions — check `InvalidStatusTransition` coverage |
| `backend/app/api/v1/calendar.py` | Calendar CRUD, reorder, upcoming items — check date timezone handling |
| `backend/app/api/v1/approvals.py` | Approval workflow — check status transition validation, reviewer authorization |
| `backend/app/api/v1/products.py` | Product CRUD, BC sync, image gallery, batch fetch — check file upload validation, gallery index bounds |
| `backend/app/api/v1/users.py` | User CRUD, Entra ID search, bulk grant access — check permission escalation |
| `backend/app/api/v1/system.py` | Health checks, scheduler jobs, audit log, service status — check information disclosure |
| `backend/app/api/v1/webhooks.py` | n8n publish result callback — check webhook secret validation (constant-time compare) |
| `backend/app/api/v1/files.py` | MinIO file proxy — check path traversal prevention, bucket parsing |
| `backend/app/deps.py` | Auth dependency — check user auto-provisioning logic, security group elevation |
| `backend/app/auth/entra.py` | JWT validation, Graph API — check JWKS caching, token cache thread safety, OData filter injection |
| `backend/app/services/nats_service.py` | NATS stream management — check stream subject list completeness |
| `backend/app/services/minio_service.py` | Object storage — check bucket creation race, secure=False |
| `backend/app/services/gemini_service.py` | DuckDuckGo scraping, Gemini image editing — check URL validation, image size limits |
| `backend/app/services/ai_model_service.py` | Model discovery, Valkey caching — check cache invalidation |
| `backend/app/scheduler/__init__.py` | APScheduler setup — check timezone handling, job replace_existing |
| `frontend/src/app/page.tsx` | Dashboard — check data fetching, error states |
| `frontend/src/components/content/KanbanBoard.tsx` | Drag-and-drop content management — check DnD state management |
| `frontend/src/components/content/ContentEditor.tsx` | Content editing — check form validation |
| `frontend/src/components/content/ChannelPreview.tsx` | Platform preview rendering — check XSS in rendered content |
| `frontend/src/components/content/PlatformMockups.tsx` | Mockup image display |
| `frontend/src/components/brand/BrandOnboarding.tsx` | Brand onboarding wizard — check validation completeness |
| `frontend/src/components/brand/BrandForm.tsx` | Brand edit form |
| `frontend/src/stores/brand-store.ts` | Zustand state — check persistence, race conditions |

### LOW PRIORITY (Config, types, UI primitives)

| File | Audit Focus |
|---|---|
| `backend/app/config.py` | Settings validation — check default values, production guards |
| `backend/app/models/base.py` | Engine config — check pool_size adequacy |
| `backend/app/models/*.py` | ORM models — check column types match init.sql |
| `backend/app/schemas/*.py` | Pydantic schemas — check optional/required field alignment |
| `frontend/src/types/index.ts` | TypeScript interfaces — check alignment with backend responses |
| `frontend/src/components/ui/*.tsx` | shadcn/ui primitives — low risk, mostly unchanged from upstream |
| `frontend/src/lib/utils.ts` | Utility functions |
| `litellm/config.yaml` | LiteLLM proxy config — check model list, cache settings |
| `observability/**` | Monitoring configs — check scrape intervals, retention |
| `traefik/**` | Reverse proxy config |
| `.github/workflows/ci.yml` | CI pipeline — check coverage gaps |
| `docker-compose*.yml` | Container orchestration — check resource limits, health checks |
| `.env.example` | Environment template — check documented defaults |

---

## 5. DEPENDENCY & VERSION AUDIT DIRECTIVES

Audit each dependency for:

1. **Security vulnerabilities:** Run `pip-audit` on all Python services and `npm audit` on frontend. Check for known CVEs in the exact versions pinned in lock files.

2. **Version currency:** Many dependencies use `>=` minimum version constraints without upper bounds. Check if the resolved versions (from Docker builds) have breaking changes or deprecations.

3. **Unused dependencies:**
   - `bcrypt>=4.0` in backend — Azure AD handles all authentication; verify bcrypt is actually used anywhere.
   - `langchain-openai>=1.0` in agents — LLM calls go through httpx to LiteLLM proxy, not langchain-openai. Verify if this is still needed.
   - `litellm>=1.60` in agents — imported but the actual LLM calls use httpx directly to the LiteLLM proxy URL. Verify if the litellm package is used directly anywhere.

4. **Duplicate dependencies:** Both backend and agents have their own `asyncpg`, `sqlalchemy`, `minio`, `qdrant-client`, `httpx`, `pydantic`, `pydantic-settings`. Verify they resolve to compatible versions.

5. **Frontend specific:**
   - `next-auth@4.24.11` with Next.js 16 — NextAuth v4 is legacy; v5 (Auth.js) is the recommended version for App Router.
   - `@auth/core@0.37.4` is installed but NextAuth v4 is configured — potential conflict.
   - Check if `postcss` should be a devDependency.

6. **Python version:** All Dockerfiles use `python:3.13-slim`. Verify all dependencies support Python 3.13.

---

## 6. AI/ML AUDIT DIRECTIVES

### LangGraph Workflows

Audit each workflow for:

1. **Graph structure correctness:** Every graph uses `_check_failed` conditional edges. Verify that failed states are properly propagated and never silently swallowed.

2. **State management:** TypedDict states use `total=False` — all fields are optional. Verify nodes handle missing keys gracefully with `.get()` and don't raise KeyError.

3. **LLM output parsing:** `parse_llm_json()` in `agents/shared/llm.py` handles markdown fences and single-key dict unwrapping. Verify all nodes that call `chat_completion` properly handle:
   - Empty responses
   - Invalid JSON
   - Truncated responses (check max_tokens adequacy)
   - Wrapped responses (`{"items": [...]}` vs bare `[...]`)

4. **Planning calendar generation** (`agents/workflows/planning/nodes.py`):
   - Weekly batch loop: verify `current_dt < end_date_dt` loop terminates correctly
   - Dedup context: `_build_dedup_context()` combines `existing_items + all_items` — verify it uses the last 60 items correctly
   - `CalendarItemValidator`: verify Pydantic validation catches all invalid LLM outputs
   - Status set to `"planned"` in store_calendar but `"queued"` is what the DB CHECK constraint expects — **verify this is correct**

5. **Content generation** (`agents/workflows/content/nodes.py`):
   - 10-node pipeline — verify each node's error handling doesn't leave orphaned state
   - Image generation with fallback: verify the `generate_image()` model fallback chain
   - Product image sourcing: verify the flow handles "no product images available" gracefully
   - Branding overlay: verify logo PNG rendering from SVG works in Docker (ImageMagick dependency)
   - Platform adaptations: verify all 8 channels produce valid adaptations

### LiteLLM Proxy Configuration

1. **Model list** (`litellm/config.yaml`): 15 models configured. Verify:
   - All model names are valid and resolvable
   - Gemini models use correct provider prefix (`gemini/` not `openai/`)
   - Video models (sora-2, sora-2-pro) are listed but may not be used — verify

2. **Cache configuration:** Redis/Valkey cache enabled. Verify cache key collision avoidance between different model calls.

3. **Timeout:** `request_timeout: 120` seconds. But `agents/shared/llm.py` uses dynamic timeouts up to 600s. Verify LiteLLM doesn't cut off long-running requests.

4. **`drop_params: true`:** LiteLLM drops unsupported parameters silently. Verify this doesn't cause unexpected behavior with model-specific features.

### Model Selection System

1. **Dynamic resolution** (`agents/shared/llm.py:get_model_for_category()`): Fetches active model from backend API, caches 5 minutes, falls back to hardcoded defaults. Verify:
   - Cache invalidation when admin changes active model
   - Fallback models (`gpt-5.4`, `gpt-5.4-mini`, `gpt-image-1.5`, `text-embedding-3-small`) are valid
   - The `openai/` prefix is correctly applied

2. **Image generation bypass** (`agents/shared/llm.py:generate_image()`): Goes directly to OpenAI API, not through LiteLLM. Verify:
   - `OPENAI_API_KEY` is available in the agents container
   - Fallback from selected model to `dall-e-3` works correctly
   - 180s timeout is sufficient for image generation

### Prompt Engineering

1. **Sanitization:** `agents/shared/sanitize.py` and duplicated in `backend/app/api/v1/intelligence.py`. Verify:
   - 9 injection patterns are comprehensive
   - `max_length=10000` truncation is applied consistently
   - All user-provided text passes through sanitization before LLM prompts

2. **System prompts:** Audit all `"role": "system"` messages in:
   - `agents/workflows/planning/nodes.py` (campaign planner, calendar planner, strategy document)
   - `agents/workflows/content/nodes.py` (hook, caption, hashtags, adaptations)
   - `agents/workflows/research/nodes.py` (competitor analysis, persona building)
   - `agents/workflows/strategy/nodes.py` (positioning, pillars, audiences, themes)
   - `backend/app/api/v1/intelligence.py` (field generation, field rewrite)

3. **JSON mode:** Several calls use `response_format={"type": "json_object"}`. Verify all such calls have system prompts that instruct JSON output.

---

## 7. SECURITY AUDIT DIRECTIVES

### Authentication & Authorization

1. **Azure AD JWT validation** (`backend/app/auth/entra.py`):
   - JWKS client is cached globally (`_jwks_client`). Verify `invalidate_jwks_cache()` is called on key rotation. Currently it's defined but **never called** — potential stale key issue.
   - `validate_entra_token()` uses `asyncio.to_thread(client.get_signing_key_from_jwt, token)` — verify this doesn't block the event loop.
   - Issuer check: `https://login.microsoftonline.com/{tenant_id}/v2.0` — verify this matches the token issuer for all supported auth flows.

2. **User auto-provisioning** (`backend/app/deps.py`):
   - Users in the admin security group are auto-provisioned as `admin` with `is_active=True`.
   - Users NOT in the group are provisioned as `viewer` with `is_active=False`.
   - **Existing users** in the security group are auto-elevated to admin — verify this is intentional and cannot be exploited.
   - Fallback: if Graph API group check fails, the user is NOT elevated — good.

3. **Role hierarchy** (`backend/app/auth/permissions.py`):
   - `admin(100) > manager(80) > editor(60) > viewer(10)`
   - `require_role_dependency()` is defined but appears unused — all endpoints use `role_has_access()` directly.

4. **Frontend auth** (`frontend/src/lib/auth.ts`):
   - Uses `id_token` for backend auth (audience = client ID), NOT the `access_token` (audience = graph.microsoft.com). Verify this is correct.
   - Token refresh: if refresh fails, sets `error: "RefreshAccessTokenError"` but doesn't force sign-out. Verify the frontend handles this.
   - Role caching: fetches from `/api/v1/users/me` and caches in JWT. If backend is unreachable, **defaults to "manager" role** — this is a security risk if the backend is temporarily down.

5. **API rate limiting** (`backend/app/main.py`):
   - Global: `120/minute` via slowapi
   - Brand activation: `5/minute`
   - AI field generation: `10/minute`
   - Product image upload: `20/minute`
   - Verify rate limits are applied per-user or per-IP correctly.

### Input Validation & Sanitization

6. **Path traversal** (`backend/app/api/v1/files.py`):
   - Blocks `..` and leading `/` in file paths — good.
   - Parses bucket from first path segment against `KNOWN_BUCKETS` whitelist — good.
   - Verify there are no other ways to access arbitrary MinIO objects.

7. **Webhook authentication** (`backend/app/api/v1/webhooks.py`):
   - Uses `secrets.compare_digest()` for constant-time comparison — good.
   - Rejects if `N8N_WEBHOOK_SECRET` is not configured — good.

8. **CORS** (`backend/app/main.py`):
   - `allow_origins` set to `[FRONTEND_URL]` only — good.
   - `allow_credentials=True` with specific origins — correct pattern.
   - Global exception handler manually sets CORS headers — verify this doesn't allow origin spoofing.

9. **Sensitive data in responses:**
   - `_strip_sensitive_guidelines()` in `brands.py` removes `access_token`, `api_key`, `refresh_token`, `webhook_url`, `client_secret` from brand_guidelines JSONB. Verify this list is complete.
   - Global exception handler sanitizes traceback lines containing secret-related words.
   - The `/api/v1/providers/active` endpoint requires **no authentication** — verify it only returns model IDs (not API keys).

10. **SQL Injection:**
    - Multiple endpoints use `text()` raw SQL: `analytics.py`, `dashboard.py`, `system.py`, `intelligence.py`, `settings.py`.
    - All appear to use parameterized queries (`:param` style) — verify none use string interpolation.
    - `agents/shared/tools/database.py` also uses `text()` extensively — verify parameterization.

11. **OData filter injection** (`backend/app/auth/entra.py:search_graph_users()`):
    - Query is sanitized: strips control chars, escapes backslashes and single quotes.
    - Verify this is sufficient for Microsoft Graph API OData filter syntax.

### Secrets Management

12. **Production startup validation** (`backend/app/config.py`):
    - Checks `SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY` are not defaults — good.
    - Checks Azure AD config is present — good.
    - **Raises RuntimeError** on violation, preventing startup — good.
    - Same pattern in `agents/shared/config.py` for `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`, `LITELLM_MASTER_KEY`.

13. **`.env` file:** Listed in `.gitignore`? Verify. The `.env.example` contains placeholder values only — good.

14. **MinIO `secure=False`** in `backend/app/services/minio_service.py` — MinIO is internal (Docker network), but verify this is intentional and not used externally.

---

## 8. DATABASE & DATA LAYER AUDIT DIRECTIVES

### Schema (from `db/init.sql`)

16 tables with proper foreign keys, indexes, and constraints:

| Table | Key Fields | Relationships | Indexes |
|---|---|---|---|
| `users` | id, entra_object_id (UNIQUE), email (UNIQUE), role (CHECK), is_active | → notifications | role |
| `brands` | id, slug (UNIQUE), status (CHECK: onboarding/activating/active/inactive), is_bc_linked, bc_company, brand_guidelines (JSONB) | → users (created_by) | created_by, bc_company, status |
| `products` | id, brand_id, bc_item_no, name, is_active, is_new, is_expiring_soon, image_urls (JSONB) | → brands (CASCADE) | brand_bc_item (UNIQUE partial), brand_id, category, sku, tags (GIN) |
| `campaigns` | id, brand_id, name, objective (CHECK), status (CHECK) | → brands (CASCADE), → users | brand_id, status, dates, created_by |
| `calendar_items` | id, brand_id, channel (CHECK 8 values), item_type (CHECK 9 values), status (CHECK 9 values), scheduled_at, pillar, theme | → brands (CASCADE), → campaigns (SET NULL), → users | brand_scheduled (composite), status, channel, many more |
| `content` | id, calendar_item_id, brand_id, version, caption, hashtags (TEXT[]), image_urls (JSONB), generation_metadata (JSONB), is_current | → calendar_items (CASCADE), → brands (CASCADE) | calendar_item_id, brand_id, is_current, **UNIQUE partial idx on (calendar_item_id) WHERE is_current=true** |
| `approvals` | id, content_id, calendar_item_id, reviewer_id, status (CHECK 4 values), feedback | → content (CASCADE), → calendar_items (CASCADE), → users | content_id, calendar_item_id, reviewer_id, status |
| `prompt_versions` | id, slug, category (CHECK 6 values), template, version, is_active, a_b_group | | slug, category, is_active, UNIQUE(slug, version) |
| `agent_runs` | id, agent_type, trigger (CHECK 5 values), status (CHECK 5 values), tokens_used, cost_usd, brand_id | → brands (CASCADE), → users, → prompt_versions | agent_type, status, brand_id, created_at, **UNIQUE partial idx on (brand_id, agent_type) WHERE status='running'** |
| `engagement_metrics` | id, content_id, calendar_item_id, brand_id, channel, impressions/reach/likes/comments/shares/saves/clicks | → content (CASCADE), → calendar_items (CASCADE), → brands (CASCADE) | content_id, brand_id, channel, fetched_at |
| `competitors` | id, brand_id, name, social_handles (JSONB), monitoring_config (JSONB) | → brands (CASCADE) | brand_id, is_active |
| `adaptations` | id, source_content_id, target_channel (CHECK), adapted_text, status (CHECK 10 values) | → content (CASCADE) | source_content_id, target_channel, status |
| `scheduled_job_log` | id, job_name, job_type, status (CHECK), duration_ms | | job_name, job_type, status, started_at |
| `audit_log` | id, user_id, action, entity_type, entity_id, old_values (JSONB), new_values (JSONB), ip_address (INET) | → users | user_id, action, entity_type, entity_id, created_at |
| `notifications` | id, user_id, title, notification_type (CHECK 10 values), channel (CHECK), is_read | → users (CASCADE) | user_id, type, is_read, user_unread (partial), created_at |
| `ai_model_categories` | id, slug (UNIQUE), display_name | | — |
| `ai_models` | id, provider, model_id, category_id, is_available | → ai_model_categories | provider, category_id, is_available, UNIQUE(provider, model_id) |
| `ai_model_selections` | id, category_slug, model_id, is_active, priority | → ai_model_categories, → ai_models, → users | category_slug, is_active, UNIQUE(category_slug, model_id) |
| `app_settings` | key (PK), value (JSONB), updated_by | → users | — |

### Audit Checks

1. **ORM ↔ Schema alignment:** Verify every SQLAlchemy model in `backend/app/models/` and `backend/app/auth/models.py` matches the `init.sql` schema exactly (column names, types, constraints).

2. **Missing models:** Verify ORM models exist for all 16+ tables. Check if `ai_model_categories`, `ai_model_selections`, `scheduled_job_log`, `audit_log`, `app_settings` have proper ORM models or are only accessed via raw SQL.

3. **Connection pooling:**
   - Backend: `pool_size=20, max_overflow=10` at `backend/app/models/base.py`
   - Agents: `pool_size=10, max_overflow=20` at `agents/shared/tools/database.py`
   - Verify these are adequate for concurrent load.

4. **Transaction management:** Check that all multi-step DB operations use proper transactions. Specifically:
   - `store_calendar_items()` in planning nodes — batch insert
   - `store_content_node()` in content nodes — content + calendar_item update
   - `resolve_approval()` — approval + calendar_item status update
   - Brand activation — brand status + agent_run creation

5. **Partial unique indexes:**
   - `idx_agent_runs_running` on `(brand_id, agent_type) WHERE status='running'` — prevents duplicate running workflows. Worker catches `IntegrityError`.
   - `idx_content_current` on `(calendar_item_id) WHERE is_current=true` — only one current content per calendar item.
   - Verify these are properly handled in application code.

6. **Calendar item status values:** The CHECK constraint allows: `queued, working, in_review, reworking, approved, scheduled, publishing, published, failed`. But `store_calendar` in planning nodes sets status to `"planned"` — **this will violate the CHECK constraint**. Verify if this was fixed or if the constraint was updated.

7. **Auto-updated_at trigger:** Applied to all tables with `updated_at` column via dynamic DO block. Verify it works correctly with SQLAlchemy's `onupdate=func.now()`.

---

## 9. API ENDPOINT AUDIT DIRECTIVES

### Complete Endpoint Inventory

All endpoints are mounted under `/api/v1/` via `backend/app/api/router.py`.

#### Brands (`/api/v1/brands/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/bc-companies` | Yes | any | List BC company names |
| GET | `/bc-locations?company=` | Yes | any | List BC locations for company |
| GET | `/` | Yes | any | List brands |
| GET | `/{brand_id}` | Yes | any | Get brand detail |
| POST | `/` | Yes | manager | Create brand |
| PUT | `/{brand_id}` | Yes | manager | Update brand |
| POST | `/{brand_id}/complete-onboarding` | Yes | manager | Validate and complete onboarding |
| POST | `/{brand_id}/activate` | Yes | manager | Start Content Factory pipeline (rate: 5/min) |
| GET | `/{brand_id}/channels` | Yes | any | Get channel config |
| PUT | `/{brand_id}/channels` | Yes | manager | Update channel config |
| POST | `/{brand_id}/logos` | Yes | manager | Upload logo |
| GET | `/{brand_id}/logos/{label}` | **No** | — | Serve logo (public, for img tags) |
| DELETE | `/{brand_id}/logos/{label}` | Yes | manager | Delete logo |
| DELETE | `/{brand_id}` | Yes | admin | Delete brand |
| GET | `/{brand_id}/competitors` | Yes | any | List competitors |
| POST | `/{brand_id}/competitors` | Yes | manager | Create competitor |
| PUT | `/{brand_id}/competitors/{id}` | Yes | manager | Update competitor |
| DELETE | `/{brand_id}/competitors/{id}` | Yes | manager | Delete competitor |

#### Content (`/api/v1/content/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/` | Yes | any | List content |
| GET | `/by-calendar-item/{id}` | Yes | any | Get content for calendar item |
| GET | `/{content_id}` | Yes | any | Get content detail |
| POST | `/` | Yes | editor | Create content |
| PUT | `/{content_id}` | Yes | editor | Update content |
| POST | `/{content_id}/regenerate-image` | Yes | editor | Trigger image regeneration |
| POST | `/{content_id}/transition` | Yes | editor | Transition content status |

#### Calendar (`/api/v1/calendar/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/upcoming` | Yes | any | Upcoming items |
| GET | `/` | Yes | any | List items (filterable) |
| GET | `/{item_id}` | Yes | any | Get item |
| POST | `/` | Yes | editor | Create item |
| PUT | `/{item_id}` | Yes | editor | Update item |
| PATCH | `/{item_id}` | Yes | editor | Partial update |
| DELETE | `/{item_id}` | Yes | editor | Delete item |
| POST | `/reorder` | Yes | editor | Reorder items |

#### Approvals (`/api/v1/approvals/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/` | Yes | any | List approvals (filterable) |
| GET | `/pending` | Yes | any | List pending approvals |
| GET | `/content/{content_id}` | Yes | any | List approvals for content |
| GET | `/{approval_id}` | Yes | any | Get approval |
| POST | `/` | Yes | editor | Create approval |
| PUT | `/{approval_id}` | Yes | manager | Decide (update) approval |
| POST | `/{approval_id}/decide` | Yes | manager | Decide approval (alias) |

#### Campaigns (`/api/v1/campaigns/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/` | Yes | any | List campaigns |
| GET | `/{campaign_id}` | Yes | any | Get campaign |
| POST | `/` | Yes | manager | Create campaign |
| PUT | `/{campaign_id}` | Yes | manager | Update campaign |
| DELETE | `/{campaign_id}` | Yes | manager | Delete campaign |

#### Products (`/api/v1/products/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| POST | `/sync/{brand_id}` | Yes | manager | Sync BC products for brand |
| GET | `/` | Yes | any | List products |
| GET | `/{product_id}` | Yes | any | Get product |
| POST | `/` | Yes | manager | Create product |
| PUT | `/{product_id}` | Yes | manager | Update product |
| POST | `/{product_id}/upload-image` | Yes | manager | Upload product image (rate: 20/min) |
| POST | `/sync` | Yes | manager | Trigger global BC sync |
| POST | `/{product_id}/fetch-images` | Yes | editor | Fetch web images for product |
| POST | `/batch-fetch-images` | Yes | editor | Batch fetch images |
| GET | `/{product_id}/images` | Yes | any | Get image gallery |
| DELETE | `/{product_id}/images/{index}` | Yes | editor | Delete gallery image |
| PUT | `/{product_id}/images/{index}/set-primary` | Yes | editor | Set primary image |

#### Intelligence (`/api/v1/intelligence/`)
| Method | Path | Auth | Role | Description |
|---|---|---|---|---|
| GET | `/reports` | Yes | any | List intelligence reports |
| GET | `/report/{run_id}` | Yes | any | Get single report |
| GET | `/trends` | Yes | any | Get trending topics |
| GET | `/research/{brand_id}` | Yes | any | Get research results |
| GET | `/adaptations/{content_id}` | Yes | any | Get adaptations for content |
| POST | `/trigger/research` | Yes | manager | Trigger research workflow |
| POST | `/trigger/strategy` | Yes | manager | Trigger strategy workflow |
| POST | `/trigger/content` | Yes | editor | Trigger content generation |
| POST | `/generate-fields` | Yes | editor | AI-generate brand fields (rate: 10/min) |
| POST | `/rewrite-field` | Yes | editor | AI-rewrite brand field (rate: 10/min) |

#### Other Endpoints
| Router | Endpoints |
|---|---|
| `/api/v1/analytics/` | summary, engagement/timeseries, posting/heatmap, content/top, brands/{id}/metrics |
| `/api/v1/dashboard/` | stats |
| `/api/v1/agents/` | runs (list agent runs) |
| `/api/v1/notifications/` | list, stream (SSE) |
| `/api/v1/prompts/` | CRUD, activate, deactivate, ab-select |
| `/api/v1/providers/` | categories, models, active (NO AUTH), active/{slug} (PUT), discover, health |
| `/api/v1/users/` | search, grant-access, security-group-members, me, CRUD, patch |
| `/api/v1/settings/` | get, put (admin only) |
| `/api/v1/system/` | health, jobs, jobs/{id}/trigger, audit-log, job-log, services, queues |
| `/api/v1/webhooks/` | publish-result (webhook secret auth) |
| `/api/v1/files/` | {path} (serve MinIO files, NO AUTH) |
| `/api/v1/learning/` | adaptations |
| `/api/v1/audit` | Alias for audit-log (defined in router.py) |
| `/health` | Root health check (NO AUTH) |
| `/metrics` | Prometheus metrics (NO AUTH) |

### Audit Checks

1. **Unauthenticated endpoints:** `/health`, `/metrics`, `/api/v1/providers/active`, `/api/v1/files/{path}`, `/api/v1/brands/{id}/logos/{label}`. Verify each is safe to expose publicly.

2. **Pagination limits:** All list endpoints cap `limit` at `min(limit, 200)` — verify this is consistent and prevents abuse.

3. **Missing DELETE endpoints:** Content has no DELETE endpoint. Verify if this is intentional.

4. **Duplicate endpoints:** Approvals has both `PUT /{id}` and `POST /{id}/decide` that do the same thing. Calendar has both `PUT` and `PATCH` that call the same service method.

---

## 10. FRONTEND & UI AUDIT DIRECTIVES

### Framework & Rendering

1. **Next.js 16 + React 19:** Verify all components use React 19 features correctly. Check for deprecated patterns.

2. **App Router:** All pages under `frontend/src/app/`. Verify:
   - Server components vs client components are correctly separated
   - `"use client"` directives are present where needed
   - Data fetching patterns are consistent

3. **Tailwind CSS 4:** Using `@tailwindcss/postcss` v4.2.2. Verify:
   - `frontend/src/app/globals.css` is properly configured
   - No Tailwind v3 config files exist (should use CSS-based config in v4)

### Key Components to Audit

1. **KanbanBoard** (`frontend/src/components/content/KanbanBoard.tsx`):
   - Uses `@dnd-kit` for drag-and-drop
   - Status columns: queued, working, in_review, approved, scheduled, published
   - Verify drop handlers correctly transition content status via API

2. **CalendarView** (`frontend/src/components/content/CalendarView.tsx`):
   - Calendar grid view of scheduled content
   - Verify date handling across timezones (system uses `Indian/Mauritius`)

3. **ContentEditor** (`frontend/src/components/content/ContentEditor.tsx`):
   - Content editing form with caption, hashtags, CTA
   - Verify form validation, unsaved changes handling

4. **ChannelPreview** (`frontend/src/components/content/ChannelPreview.tsx`):
   - Shows how content will look on each social platform
   - Verify XSS prevention when rendering user-generated content

5. **PlatformMockups** (`frontend/src/components/content/PlatformMockups.tsx`):
   - Displays AI-generated mockup images for each platform
   - Verify image loading states, error handling

6. **BrandOnboarding** (`frontend/src/components/brand/BrandOnboarding.tsx`):
   - Multi-step wizard: brand info → voice profile → channels → logos → competitors → complete
   - Verify validation at each step matches backend validation in `complete-onboarding`

7. **BrandSwitcher** (`frontend/src/components/layout/BrandSwitcher.tsx`):
   - Global brand selection via Zustand store
   - Verify state persists across navigation

### Authentication Flow

8. **Sign-in page** (`frontend/src/app/auth/signin/page.tsx`):
   - Azure AD SSO redirect
   - Verify error handling for failed auth

9. **API client** (`frontend/src/lib/api.ts`):
   - Auto-redirect to sign-in on 401 responses — verify no infinite redirect loops
   - `fileUrl()` helper rewrites legacy MinIO presigned URLs — verify regex is correct
   - Trailing slash logic uses complex regex — verify it doesn't break API calls

### Type Safety

10. **TypeScript interfaces** (`frontend/src/types/index.ts`):
    - 30+ interfaces defined. Verify alignment with actual backend API responses:
      - `Content.title` vs backend `Content.headline` — interface has both
      - `User.brand_ids` — verify this field exists in backend responses
      - `User.name` vs backend `User.display_name`
      - `PromptVersion` interface fields vs backend schema
      - `Adaptation.confidence_score` — verify backend returns this

---

## 11. TESTING AUDIT DIRECTIVES

### Existing Tests

#### Backend Tests (`backend/tests/`)
| File | Coverage |
|---|---|
| `conftest.py` | Sets `MARKAI_ENV=test`, overrides secrets |
| `test_api_health.py` | Health endpoint tests |
| `test_auth_permissions.py` | Role hierarchy verification |
| `test_utils.py` | Utility function tests |

#### Agent Tests (`agents/tests/`)
| File | Coverage |
|---|---|
| `test_llm_parsing.py` | `parse_llm_json`, `strip_markdown_fences`, `validate_llm_output` |
| `test_sanitize.py` | Prompt injection pattern detection |

### Critical Gaps

1. **No integration tests** for any API endpoint with a real database.
2. **No workflow tests** — none of the 7 LangGraph workflows have tests.
3. **No frontend tests** — no Jest/Vitest/Playwright tests exist.
4. **No end-to-end tests** for the activation pipeline.
5. **No load/performance tests**.
6. **No test for NATS message handling** in the worker.
7. **No test for image generation** or processing pipeline.
8. **No test for Fabric/BC sync** operations.

### Recommendations

- Add pytest fixtures for async DB sessions using `testcontainers` or SQLite in-memory.
- Add workflow tests with mocked LLM responses.
- Add API integration tests for all CRUD operations.
- Add frontend component tests with React Testing Library.

---

## 12. INFRASTRUCTURE & DEVOPS AUDIT DIRECTIVES

### Docker Compose

1. **Base file** (`docker-compose.yml`):
   - 15+ services with health checks on all
   - Memory limits set on all services (256M–2G)
   - Depends_on with `condition: service_healthy` for backend/agents
   - Verify logging configuration (json-file driver, 50m max-size, 5 files)

2. **VPS overlay** (`docker-compose.vps.yml`):
   - Disables bundled Traefik and n8n (uses VPS-level Traefik and shared n8n)
   - Connects to external `n8n_default` network
   - Observability stack optional via `--profile observability`
   - Verify Traefik labels are correct for auto-discovery

3. **Local dev overlay** (`docker-compose.override.yml`):
   - Binds ports to `127.0.0.1` only — good security practice
   - Hot reload volumes for backend, agents, browser-worker
   - Backend runs with `--reload` flag

### Dockerfiles

4. **Backend Dockerfile:**
   - Multi-stage build (builder → runtime)
   - Installs MSSQL ODBC driver (for Fabric SQL)
   - Runs as non-root user `appuser` (UID 1001)
   - Verify: COPY order for layer caching optimization

5. **Agents Dockerfile:**
   - Multi-stage build
   - Installs ImageMagick (for SVG→PNG logo rendering), fonts-dejavu-core
   - Installs Playwright Chromium and OS dependencies
   - Runs as non-root user
   - **Concern:** Playwright + ImageMagick + Python deps = large image. Check final image size.

6. **Frontend Dockerfile:**
   - Multi-stage: deps → builder → runner
   - `NEXT_PUBLIC_API_URL` passed as build arg (baked into JS bundle)
   - Uses standalone output mode
   - Runs as non-root user `nextjs`
   - Installs `curl` for healthcheck

### NATS JetStream

7. **Stream configuration:**
   - Single stream `WORKFLOWS` with 7+ subject patterns
   - `retention: "workqueue"`, `max_age: 7 days`
   - Durable consumers with `ack_wait: 1860s` (31 min), `max_deliver: 5`
   - Verify: worker subscribes to all required subjects

8. **Message flow:**
   - Backend publishes via `nats_service.publish()`
   - Worker subscribes via `NATSConsumer.subscribe()` with push subscriptions
   - Worker chains by publishing to the next subject after completion
   - Verify: no message loss scenarios, dead letter handling

### Health Checks

9. Verify all Docker health checks are appropriate:
   - Postgres: `pg_isready` — good
   - Qdrant: HTTP readiness check — good
   - MinIO: `curl /minio/health/live` — good
   - Valkey: `valkey-cli ping` — good
   - NATS: `wget /healthz` — good
   - LiteLLM: Python `urlopen` — functional but heavy; consider `curl`
   - Backend: `curl /health` — good
   - Frontend: `curl` with HTTP code check — good
   - Agents: `pgrep -f 'python -m worker'` — checks process exists but not health
   - Browser-worker: `curl /health` — good

### CI/CD

10. **GitHub Actions** (`.github/workflows/ci.yml`):
    - 4 jobs: backend-lint, frontend-lint, backend-test, agents-test
    - Python 3.13 for backend and agents
    - Node.js 22 for frontend
    - **No deployment step** — verify how deployments happen (manual Docker Compose?)
    - **No Docker build test** — verify Docker images build successfully in CI

---

## 13. PERFORMANCE AUDIT DIRECTIVES

### LLM Timeouts & Costs

1. **Workflow timeout:** `WORKFLOW_TIMEOUT_SECONDS=1800` (30 minutes). Verify this is sufficient for:
   - Research workflow (web crawling + 5+ LLM calls)
   - Planning workflow (year-long strategy document = 16K token generation + weekly batch calendar generation)
   - Content workflow (10 nodes including image generation)

2. **LLM call timeout scaling** (`agents/shared/llm.py`):
   - Formula: `max(120, min(600, max_tokens // 10))`
   - For `max_tokens=16384` (strategy document): timeout = 600s
   - For `max_tokens=4096` (default): timeout = 409s
   - Verify these are within LiteLLM's `request_timeout: 120` — **potential conflict!**

3. **Image generation timeout:** 180s for OpenAI API direct call. Verify this is sufficient.

### Batch Processing

4. **Calendar generation** (`agents/workflows/planning/nodes.py`):
   - Generates in 7-day batches to avoid LLM truncation
   - Each batch: one LLM call with `max_tokens=8192`
   - For `scope_weeks=12`: ~12 batches × ~10-20s per call = 2-4 minutes
   - Dedup context rebuilds every batch including previously generated items

5. **Sequential content generation** (`agents/worker.py`):
   - Generates content ONE item at a time (sequential chaining via `remaining_queue`)
   - Each content item: 10 nodes including image generation (~30-60s per item)
   - For 84 calendar items (12 weeks × 7 channels): ~42-84 minutes total
   - Verify the 30-minute workflow timeout is sufficient — **it may not be**

### Connection Pooling

6. **Backend DB pool:** `pool_size=20, max_overflow=10` — up to 30 connections
7. **Agents DB pool:** `pool_size=10, max_overflow=20, pool_pre_ping=True` — up to 30 connections
8. **Total:** Up to 60 DB connections from application code. PostgreSQL default max_connections = 100. Verify adequacy.

9. **httpx client in agents:** Shared singleton with `max_connections=20`. Verify this is sufficient for concurrent LLM calls.

### Caching

10. **Valkey caching:**
    - Dashboard stats: 5-minute TTL
    - Analytics summary: 5-minute TTL
    - AI model selections: cached in `ai_model_service.py`
    - LiteLLM response cache: configured in `litellm/config.yaml`
    - Agent model cache: 5-minute TTL in `agents/shared/llm.py`
    - Verify cache invalidation on data changes

---

## 14. CODE QUALITY & PATTERN AUDIT DIRECTIVES

### Error Handling

1. **Global exception handler** (`backend/app/main.py`):
   - Catches all unhandled exceptions
   - Sanitizes tracebacks (removes lines with secret/password/token keywords)
   - Returns generic 500 with CORS headers
   - **Concern:** sanitization by keyword matching is fragile — secrets could appear in non-obvious lines

2. **Workflow error propagation:**
   - All workflow nodes set `status: "failed"` and append to `errors` list
   - `_check_failed` conditional edges route to END on failure
   - Worker catches: `IntegrityError`, `asyncio.TimeoutError`, `GraphInterrupt`, generic `Exception`
   - Verify: failed workflows don't leave orphaned DB records

3. **API error handling:**
   - Most endpoints use try/except with HTTPException
   - Some endpoints have bare `except Exception` with rollback — verify logging
   - `intelligence.py:_call_llm()` has retry with tenacity + fallback to direct OpenAI

### Type Safety

4. **Backend:** Python type hints used throughout. `Mapped[]` column types in ORM. Pydantic schemas for API boundaries.

5. **Frontend:** TypeScript with 30+ interfaces. Check for:
   - `any` types
   - Missing null checks on optional fields
   - Type assertions (`as T`) that bypass safety

6. **Agents:** TypedDict states with `total=False`. All fields optional — high risk of missing keys.

### Code Duplication

7. **Duplicated sanitization:** Prompt injection patterns defined identically in:
   - `agents/shared/sanitize.py`
   - `backend/app/api/v1/intelligence.py`
   Consolidate to a shared location.

8. **Duplicated LLM calling:** `intelligence.py:_call_llm()` duplicates the pattern in `agents/shared/llm.py` with slightly different retry logic.

9. **Channel constants:** `ALL_CHANNELS` and `CHANNEL_DISPLAY_NAMES` defined in both:
   - `backend/app/models/brand.py`
   - `frontend/src/types/index.ts`
   - `agents/workflows/planning/nodes.py` (as `VALID_CHANNELS`)
   Verify they are in sync.

### Naming Conventions

10. **Inconsistencies:**
    - Backend uses `headline` for content title; frontend type has both `title` and `headline`
    - Backend Competitor model uses `description`; frontend/API uses `notes` (mapped in endpoint)
    - Backend User model uses `display_name`; frontend User type uses `name`
    - `entra_object_id` in DB vs `entra_id` in ORM model (mapped via `"entra_object_id"`)

---

## 15. KNOWN ISSUES PRE-LOADED

These issues were identified from commit history, TODO comments, and code analysis:

1. **Duplicate content fix** (commit `49b0b37`): Dedup context is now updated between batches in calendar generation. Verify the fix is complete — check that `_build_dedup_context()` includes ALL previously generated items.

2. **French text in old data:** Early content was generated in French due to Mauritius locale context. System prompts now explicitly say "Write all content in English." Verify all system prompts include this instruction.

3. **Image generation model compatibility** (commit `bd57dca`): Falls back to `dall-e-3` when selected model requires org verification. Verify the fallback chain works for all model variants in `litellm/config.yaml`.

4. **Calendar batch LLM responses:** LLM sometimes returns a single item dict instead of an array, or wraps the array in a dict. The code handles both cases — verify edge cases are covered.

5. **Calendar item status "planned" vs "queued":** `store_calendar` in planning nodes sets status to `"planned"` but the DB CHECK constraint on `calendar_items.status` does NOT include `"planned"` — it only allows: `queued, working, in_review, reworking, approved, scheduled, publishing, published, failed`. **This will cause an INSERT failure.** Verify if there's a migration that adds this status or if the code should use `"queued"`.

6. **MinIO secure=False:** All MinIO clients use `secure=False` because MinIO is on the internal Docker network. Verify this is acceptable and that MinIO is never exposed externally.

7. **SSE notification polling:** `backend/app/api/v1/notifications.py:stream_notifications()` polls the DB every 10 seconds instead of using NATS pub/sub or Valkey pub/sub. This is inefficient for many concurrent users.

8. **LiteLLM timeout conflict:** LiteLLM config sets `request_timeout: 120` but the agents LLM wrapper uses dynamic timeouts up to 600s. The LiteLLM proxy may kill long-running requests before the client timeout.

9. **No Alembic migrations beyond initial:** `alembic/` directory exists with `env.py` but verify if actual migration files exist or if the schema is only managed via `init.sql`.

---

## 16. CROSS-CUTTING ANALYSIS DIRECTIVES

1. **End-to-end data flow integrity:** Trace a content item from brand activation through research → strategy → planning → content generation → approval → publishing. Verify data consistency at each stage transition.

2. **Error recovery paths:** What happens when:
   - A workflow fails midway through the activation pipeline?
   - The LLM returns invalid JSON after 3 retries?
   - NATS loses a message?
   - MinIO is temporarily unavailable during image upload?
   - The browser-worker is down during research web crawling?

3. **Observability completeness:** Verify:
   - All services emit structured JSON logs
   - Prometheus metrics cover all critical paths
   - OpenTelemetry traces span across service boundaries (backend → NATS → agents)
   - Alert rules in `observability/prometheus/rules/alerts.yml` cover failure scenarios

4. **Configuration consistency:** Verify all services that share configuration (DB credentials, NATS URL, MinIO keys) use the same `.env` file and the values are consistent.

5. **Graceful degradation:** What happens when optional services are unavailable?
   - Qdrant down → vector search fails — does content generation still work?
   - LiteLLM down → LLM calls fail — is there a direct OpenAI fallback in all code paths?
   - Valkey down → cache fails — does the app still function (just slower)?
   - n8n down → publishing fails — are items stuck in "publishing" status forever?

---

## 17. AUDIT EXECUTION RULES

1. **Read every file referenced in this document** before writing any findings.
2. **Verify claims** — do not trust this document blindly. Cross-reference file paths, line numbers, and code patterns against the actual source.
3. **Prioritize:** HIGH priority files first, then MEDIUM, then LOW.
4. **Be specific:** Reference exact file paths, line numbers, function names, and variable names in all findings.
5. **Classify findings** by severity: CRITICAL (security vulnerability, data loss risk), HIGH (bug, performance issue), MEDIUM (code smell, maintainability), LOW (style, documentation).
6. **Provide fixes:** Every finding must include a concrete, implementable fix — not just a description of the problem.
7. **Test your assumptions:** If you suspect a bug, trace the code path to confirm it before reporting.
8. **Check both directions:** For every integration point, verify both the producer and consumer handle edge cases.

---

## 18. OUTPUT REQUIREMENTS

Produce a structured audit report with:

1. **Executive Summary** (1 paragraph): Overall health assessment, critical findings count, top 3 risks.

2. **Critical Findings** (if any): Security vulnerabilities, data loss risks, production blockers.

3. **High-Priority Findings**: Bugs, performance issues, reliability concerns.

4. **Medium-Priority Findings**: Code smells, maintainability issues, inconsistencies.

5. **Low-Priority Findings**: Style, documentation, minor improvements.

6. **Remediation Plan**: Prioritized list of fixes with estimated effort (hours) and dependencies.

7. **Architecture Recommendations**: Structural improvements for scalability, reliability, and maintainability.

8. **Testing Recommendations**: Specific tests to add, organized by priority.

Each finding must include:
- **ID**: Sequential (e.g., C-01 for critical, H-01 for high)
- **Title**: One-line summary
- **Location**: File path and line number(s)
- **Description**: What the issue is and why it matters
- **Evidence**: Code snippet or trace showing the problem
- **Fix**: Concrete implementation instructions
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Effort**: Estimated hours to fix

---

*Generated from full codebase analysis on 2026-04-01. All file paths, dependency versions, endpoint inventories, and code patterns are sourced directly from the MARKAI repository.*
