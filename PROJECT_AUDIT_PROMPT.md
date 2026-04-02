# PROJECT AUDIT PROMPT — MARKAI

> **This document is a hyper-specific, codebase-aware audit prompt generated from a full reconnaissance of the MarkAI repository on 2026-04-02. An auditing agent reading this document should be able to execute a world-class audit without asking a single clarifying question.**

---

## 1. PROJECT CONTEXT BRIEFING

**What MarkAI Does:**
MarkAI is an **AI-powered marketing automation platform** for multi-brand, multi-channel social media content creation, scheduling, approval, and publishing. It serves a retail/FMCG business in Mauritius, integrating with Microsoft Business Central (ERP) for product data, Microsoft Fabric/Power BI for analytics, and multiple social media platforms (Instagram, Facebook, LinkedIn, YouTube, TikTok, X/Twitter) for publishing. The system uses LangGraph-based AI agents to autonomously research trends, generate marketing strategies, create content (text + images), adapt content per channel, and learn from engagement metrics.

**Architecture Summary:**
MarkAI is a **containerized microservices application** running 16+ Docker services orchestrated via Docker Compose. The architecture consists of:

1. **Frontend** (Next.js 16.2.1 / React 19.2.4 / TypeScript 5.7.2) — Single-page app with App Router, Zustand state, Radix UI components, Tailwind CSS 4.2.2, NextAuth 4.24.11 with Azure AD SSO.
2. **Backend API** (FastAPI >=0.135 / Python 3.13) — REST API with SQLAlchemy 2.0+ async ORM, Pydantic validation, JWT auth via Microsoft Entra ID, APScheduler for cron jobs, NATS JetStream for async messaging.
3. **AI Agents Worker** (LangGraph >=1.0 / Python 3.13) — 7 workflow pipelines (research, strategy, planning, content, adaptation, evaluation, product_intel) consuming NATS messages, using LiteLLM as unified LLM gateway.
4. **Browser Worker** (FastAPI / Playwright 1.58+ / Python 3.13) — Headless Chromium service for web scraping, screenshot capture, and product image fetching.
5. **Notifications Service** (FastAPI / Python 3.13) — SSE streaming + Microsoft Teams webhook notifications.
6. **Infrastructure Services** — PostgreSQL 16, Qdrant v1.17.0 (vector DB), MinIO (S3-compatible object storage), Valkey 9.0.3 (Redis-compatible cache), NATS 2.12.5 (JetStream message broker), LiteLLM v1.82.3 (LLM proxy), n8n 1.82.1 (workflow automation for social publishing), Traefik v3.6 (reverse proxy).
7. **Observability Stack** — Prometheus v3.10.0, Grafana 12.4.1, Loki 3.6.7, Promtail 3.6.7, OpenTelemetry Collector 0.147.0.

**How to Build and Run:**
```bash
# Local development (all 16+ services)
docker compose up --build

# VPS production deployment
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --build

# Run backend tests
cd backend && pip install -e ".[dev]" && pytest tests/ -v

# Run agents tests
cd agents && pip install -e ".[dev]" && pytest tests/ -v

# Run frontend lint + type check
cd frontend && npm ci && npm run lint && npx tsc --noEmit
```

**Deployment Model:**
- **Local dev:** `docker-compose.yml` + `docker-compose.override.yml` (auto-loaded) with host port bindings and hot reload.
- **Production:** VPS with `docker-compose.vps.yml` overlay, external Traefik on shared `n8n_default` Docker network, no host port bindings.
- **CI/CD:** GitHub Actions (`.github/workflows/ci.yml`) — 4 jobs: backend-lint (Ruff), frontend-lint (ESLint + tsc), backend-test (pytest), agents-test (pytest).

**Maturity Assessment: Growing Product (early-to-mid stage)**
- Evidence: Well-structured architecture, enterprise integrations (Entra ID, Business Central, Fabric), full observability stack.
- But: Only ~256 lines of test code (~1-2% coverage), no migration versions committed, no soft deletes, some raw SQL, production secrets committed to repository.

**Known Technical Debt:**
- Production `.env` file with real secrets is committed to git history.
- No Alembic migration versions — schema managed only via `db/init.sql`.
- Zero frontend tests.
- No TODO/FIXME/HACK comments found (either cleaned up or never added).
- Multiple endpoints with duplicate logic (PUT/PATCH for calendar and users).
- `app_settings` table has no SQLAlchemy model — managed via raw SQL.
- Inconsistent rate limiting (only a few endpoints have specific limits).

**What Works Well:**
- Clean separation of concerns across services.
- Consistent use of Pydantic schemas for request/response validation.
- Good use of `selectinload()` in several critical query paths.
- Proper multi-stage Docker builds with non-root users and healthchecks.
- Comprehensive observability stack (Prometheus, Grafana, Loki, OpenTelemetry).
- Well-designed RBAC system (admin > manager > editor > viewer).
- Proper use of `secrets.compare_digest()` for webhook verification.

---

## 2. TECH STACK & DEPENDENCY MANIFEST

### RUNTIME & FRAMEWORK

| Component | Technology | Version |
|-----------|-----------|---------|
| Frontend Runtime | Node.js | 22 (Alpine) |
| Frontend Framework | Next.js | 16.2.1 |
| Frontend Language | TypeScript | 5.7.2 |
| Frontend React | React | 19.2.4 |
| Backend Runtime | Python | 3.13 (Slim) |
| Backend Framework | FastAPI | >=0.135 |
| Backend Server | Uvicorn | standard extras |
| ORM | SQLAlchemy | >=2.0.48 (async) |
| Migration Tool | Alembic | >=1.18 |
| Agent Framework | LangGraph | >=1.0, <2.0 |
| LLM Gateway | LiteLLM | v1.82.3-stable.patch.2 |

### CORE BACKEND DEPENDENCIES (runtime)

| Package | Min Version | Used For |
|---------|-------------|----------|
| fastapi[standard] | >=0.135 | REST API framework, all endpoints in `backend/app/api/v1/` |
| uvicorn[standard] | latest | ASGI server for FastAPI |
| sqlalchemy[asyncio] | >=2.0.48 | Async ORM for PostgreSQL, all models in `backend/app/models/` |
| asyncpg | >=0.31 | PostgreSQL async driver |
| alembic | >=1.18 | Database migrations (configured but no versions committed) |
| pydantic | >=2.12 | Request/response validation, all schemas in `backend/app/schemas/` |
| pydantic-settings | >=2.13 | Environment variable configuration in `backend/app/config.py` |
| PyJWT[crypto] | latest | JWT token verification for Entra ID auth in `backend/app/deps.py` |
| httpx | >=0.28 | HTTP client for Microsoft Graph API, Fabric, external calls |
| pyodbc | >=5.3 | MSSQL driver for Business Central via Fabric SQL endpoint |
| apscheduler | >=3.11 | Cron job scheduling in `backend/app/scheduler/` |
| nats-py | >=2.14 | NATS JetStream messaging in `backend/app/services/nats_service.py` |
| minio | >=7.2 | S3-compatible object storage in `backend/app/services/minio_service.py` |
| qdrant-client | >=1.17 | Vector DB client in `backend/app/services/qdrant_service.py` |
| litellm | >=1.60 | Unified LLM interface (backend-side) |
| redis | >=7.1 | Valkey cache client |
| python-multipart | >=0.0.18 | File upload handling |
| google-genai | >=1.5 | Google Gemini direct API in `backend/app/services/gemini_service.py` |
| Pillow | >=12.0 | Image processing |
| bcrypt | >=4.0 | Password hashing (not currently used — auth is Entra ID SSO) |
| opentelemetry-api | >=1.40 | Distributed tracing API |
| opentelemetry-sdk | >=1.40 | Tracing SDK |
| opentelemetry-instrumentation-fastapi | >=0.61b0 | Auto-instrument FastAPI |
| opentelemetry-exporter-otlp | >=1.40 | Export traces to OTel Collector |
| slowapi | >=0.1.9 | Rate limiting in `backend/app/main.py` |
| prometheus-fastapi-instrumentator | >=7.0 | Prometheus metrics endpoint |
| python-json-logger | >=3.0 | Structured JSON logging |
| tenacity | >=8.2 | Retry decorator for external calls |

### CORE AGENTS DEPENDENCIES (runtime)

| Package | Min Version | Used For |
|---------|-------------|----------|
| langgraph | >=1.0, <2.0 | AI workflow graph framework in `agents/workflows/` |
| langchain-core | >=1.0, <2.0 | LLM chain primitives |
| langchain-openai | >=1.0, <2.0 | OpenAI integration via LangChain |
| litellm | >=1.60 | Unified LLM calls in `agents/shared/llm.py` |
| nats-py | >=2.14 | Message consumption in `agents/worker.py` |
| asyncpg | >=0.31 | Direct DB access from agents |
| sqlalchemy[asyncio] | >=2.0.48 | ORM queries in `agents/shared/tools/database.py` |
| httpx | >=0.28 | HTTP calls to backend API and external services |
| pyodbc | >=5.3 | Business Central MSSQL queries in `agents/shared/tools/fabric.py` |
| minio | >=7.2 | Asset storage in `agents/shared/tools/storage.py` |
| qdrant-client | >=1.17 | Vector search in `agents/shared/tools/vector.py` |
| playwright | >=1.58 | Browser automation in `agents/shared/tools/browser.py` |
| pydantic | >=2.12 | State/config validation |
| pydantic-settings | >=2.13 | Environment config in `agents/shared/config.py` |
| opentelemetry-api | >=1.40 | Tracing |
| opentelemetry-sdk | >=1.40 | Tracing SDK |
| google-genai | >=1.5 | Google Gemini direct API |
| Pillow | >=12.0 | Image processing in `agents/shared/image_processing.py` |
| numpy | >=2.0 | Numerical operations |
| tenacity | >=9.0 | Retry logic |
| python-json-logger | >=3.0 | Structured logging |

### CORE FRONTEND DEPENDENCIES (runtime)

| Package | Version | Used For |
|---------|---------|----------|
| next | ^16.2.1 | App router framework |
| react | ^19.2.4 | UI rendering |
| react-dom | ^19.2.4 | DOM rendering |
| next-auth | ^4.24.11 | Azure AD SSO in `frontend/src/app/api/auth/[...nextauth]/route.ts` |
| @auth/core | ^0.37.4 | Auth core for NextAuth |
| zustand | ^5.0.3 | Brand state management in `frontend/src/stores/brand-store.ts` |
| @radix-ui/react-avatar | ^1.1.2 | User avatars |
| @radix-ui/react-dialog | ^1.1.4 | Modal dialogs |
| @radix-ui/react-dropdown-menu | ^2.1.4 | Dropdown menus |
| @radix-ui/react-label | ^2.1.1 | Form labels |
| @radix-ui/react-select | ^2.1.4 | Select dropdowns |
| @radix-ui/react-separator | ^1.1.1 | Dividers |
| @radix-ui/react-slot | ^1.1.1 | Polymorphic components |
| @radix-ui/react-switch | ^1.2.6 | Toggle switches |
| @radix-ui/react-tabs | ^1.1.2 | Tabbed navigation |
| @radix-ui/react-tooltip | ^1.1.6 | Tooltips |
| @dnd-kit/core | ^6.3.1 | Drag-and-drop (Kanban board) |
| @dnd-kit/sortable | ^10.0.0 | Sortable lists |
| @dnd-kit/utilities | ^3.2.2 | DnD utilities |
| class-variance-authority | ^0.7.1 | Component variant definitions |
| clsx | ^2.1.1 | Conditional classnames |
| tailwind-merge | ^2.6.0 | Tailwind class deduplication |
| date-fns | ^4.1.0 | Date formatting in `frontend/src/lib/utils.ts` |
| lucide-react | ^0.468.0 | Icon library |
| recharts | ^3.8.1 | Analytics charts in `frontend/src/components/analytics/` |
| react-markdown | ^10.1.0 | Markdown rendering in `frontend/src/components/ui/safe-render.tsx` |
| sonner | ^2.0.7 | Toast notifications |
| next-themes | ^0.4.4 | Dark/light mode |
| postcss | ^8.4.49 | CSS processing |

### FRONTEND DEV DEPENDENCIES

| Package | Version | Used For |
|---------|---------|----------|
| tailwindcss | ^4.2.2 | Utility-first CSS framework |
| @tailwindcss/postcss | ^4.2.2 | PostCSS plugin for Tailwind v4 |
| typescript | ^5.7.2 | Type checking |
| eslint | ^9.17.0 | Linting |
| eslint-config-next | ^16.2.1 | Next.js ESLint rules |
| @types/node | ^25.5.0 | Node.js type definitions |
| @types/react | ^19.2.14 | React type definitions |
| @types/react-dom | ^19.2.3 | ReactDOM type definitions |

### BROWSER WORKER DEPENDENCIES

| Package | Min Version | Used For |
|---------|-------------|----------|
| fastapi[standard] | >=0.135 | HTTP service |
| uvicorn[standard] | latest | ASGI server |
| playwright | >=1.58 | Headless Chromium browser |
| httpx | >=0.28 | HTTP requests |
| minio | >=7.2 | Image storage |
| pydantic | >=2.12 | Config validation |
| pydantic-settings | >=2.13 | Environment config |
| beautifulsoup4 | >=4.14 | HTML parsing in `browser-worker/app/social_scraper.py` |
| Pillow | >=12.1 | Image processing |

### NOTIFICATIONS DEPENDENCIES

| Package | Min Version | Used For |
|---------|-------------|----------|
| fastapi[standard] | >=0.135 | HTTP service |
| uvicorn[standard] | latest | ASGI server |
| httpx | >=0.28 | HTTP requests to Teams webhook |
| asyncpg | >=0.31 | PostgreSQL queries |
| sqlalchemy[asyncio] | >=2.0.48 | ORM |
| pydantic | >=2.12 | Validation |
| pydantic-settings | >=2.13 | Environment config |
| sse-starlette | >=3.3 | Server-Sent Events streaming |
| valkey | >=6.1 | Redis-compatible pub/sub |

### IMPLICIT DEPENDENCIES (infrastructure)

| Component | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 16-alpine | Primary relational database |
| Qdrant | v1.17.0 | Vector embeddings & similarity search |
| MinIO | RELEASE.2025-01-20 | S3-compatible object storage |
| Valkey | 9.0.3-alpine | Redis-compatible cache |
| NATS | 2.12.5-alpine (JetStream) | Async message broker |
| LiteLLM | v1.82.3-stable.patch.2 | Unified LLM gateway proxy |
| n8n | 1.82.1 | Social media publishing workflows |
| Traefik | v3.6 | Reverse proxy (dev only) |
| Prometheus | v3.10.0 | Metrics collection |
| Grafana | 12.4.1 | Dashboards & alerting |
| Loki | 3.6.7 | Log aggregation |
| Promtail | 3.6.7 | Log shipper |
| OpenTelemetry Collector | 0.147.0 | Distributed tracing |
| ODBC Driver 17 | latest | SQL Server driver for Business Central |

### DEPENDENCY AUDIT INSTRUCTIONS

For **EVERY** dependency listed above, the auditing agent must:
1. Web search `"[package name] latest stable version [current year]"` — individually, not in bulk
2. Compare the current minimum version to the latest stable release
3. Check for security advisories: search `"[package name] CVE"` or `"[package name] security advisory"`
4. Check if package is deprecated or abandoned (last release > 2 years ago)
5. Note breaking changes if more than 1 major version behind
6. For Python packages, run: `pip-audit` (if available) or check PyPI advisories
7. For npm packages, run: `npm audit` in the `frontend/` directory
8. Flag any package that has known vulnerabilities at the pinned version

---

## 3. ARCHITECTURE MAP

### DIRECTORY STRUCTURE

```
/MarkAI/
├── agents/                           # LangGraph AI agent worker service
│   ├── shared/                       # Shared utilities across all workflows
│   │   ├── config.py                 # Pydantic settings (env vars)
│   │   ├── image_processing.py       # Image resize/optimize utilities
│   │   ├── llm.py                    # LiteLLM wrapper for LLM calls
│   │   ├── nats_consumer.py          # NATS JetStream consumer base class
│   │   ├── sanitize.py               # Prompt injection sanitization
│   │   ├── state.py                  # Shared agent state definitions
│   │   └── tools/                    # Agent tools (DB, web, storage, etc.)
│   │       ├── browser.py            # Playwright browser automation
│   │       ├── database.py           # Direct PostgreSQL queries
│   │       ├── fabric.py             # Microsoft Fabric/BC SQL queries
│   │       ├── image_search.py       # Web image search
│   │       ├── social.py             # Social media API integration
│   │       ├── storage.py            # MinIO file operations
│   │       ├── vector.py             # Qdrant vector operations
│   │       └── web_search.py         # Web search (via Gemini)
│   ├── workflows/                    # 7 LangGraph workflow definitions
│   │   ├── adaptation/               # Content adaptation per channel
│   │   ├── content/                  # Content generation (text + images)
│   │   ├── evaluation/               # Engagement metric analysis
│   │   ├── planning/                 # Content calendar planning
│   │   ├── product_intel/            # Product intelligence from BC
│   │   ├── research/                 # Market/competitor research
│   │   └── strategy/                 # Marketing strategy generation
│   ├── worker.py                     # NATS consumer entry point (877 lines)
│   ├── pyproject.toml                # Agent dependencies
│   ├── Dockerfile                    # Python 3.13-slim + Playwright
│   └── tests/                        # Agent tests (2 files)
│
├── backend/                          # FastAPI REST API service
│   ├── app/                          # Application code
│   │   ├── main.py                   # FastAPI app init, middleware, CORS, error handling (166 lines)
│   │   ├── config.py                 # Pydantic settings with 50+ env vars (167 lines)
│   │   ├── deps.py                   # Auth dependency injection, DB session (120 lines)
│   │   ├── api/                      # API routes
│   │   │   ├── router.py             # Main router assembler (89 lines)
│   │   │   └── v1/                   # 19 route modules (~4142 lines total)
│   │   ├── auth/                     # Authentication
│   │   │   ├── entra.py              # Microsoft Entra ID / Graph API integration
│   │   │   ├── models.py             # User, Notification, AuditLog, ScheduledJobLog models
│   │   │   └── permissions.py        # RBAC role hierarchy
│   │   ├── models/                   # SQLAlchemy models (14 model files)
│   │   ├── schemas/                  # Pydantic request/response schemas (14 files)
│   │   ├── services/                 # Business logic services (17 files)
│   │   └── scheduler/               # APScheduler cron jobs (5 files)
│   ├── alembic/                      # Database migration config (VERSIONS EMPTY)
│   ├── tests/                        # Backend tests (4 files, 118 lines)
│   ├── pyproject.toml                # Backend dependencies
│   └── Dockerfile                    # Python 3.13-slim multi-stage
│
├── browser-worker/                   # Playwright HTTP service
│   ├── app/                          # 5 source files
│   ├── pyproject.toml
│   └── Dockerfile
│
├── notifications/                    # SSE + Teams webhook service
│   ├── app/                          # 5 source files
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/                         # Next.js React application
│   ├── src/
│   │   ├── app/                      # 22 pages (Next.js App Router)
│   │   ├── components/               # 50 React components
│   │   ├── lib/                      # api.ts, auth.ts, hooks.ts, utils.ts
│   │   ├── stores/                   # brand-store.ts (Zustand)
│   │   └── types/                    # index.ts (414 lines), next-auth.d.ts
│   ├── package.json
│   └── Dockerfile                    # Node 22-alpine multi-stage
│
├── db/
│   └── init.sql                      # PostgreSQL schema (517 lines, 19 tables)
│
├── litellm/
│   └── config.yaml                   # LLM model routing
│
├── observability/                    # Prometheus, Grafana, Loki, OTel configs
├── traefik/                          # Reverse proxy config (dev)
├── scripts/                          # vps-redeploy.sh, seed-dev.py, bc/column discovery
│
├── docker-compose.yml                # Base 16-service stack (473 lines)
├── docker-compose.override.yml       # Local dev overrides (91 lines)
├── docker-compose.vps.yml            # VPS production overlay (74 lines)
├── .env                              # LIVE PRODUCTION SECRETS (COMMITTED!)
├── .env.example                      # Environment template
├── .env.vps.example                  # VPS environment template
├── .github/workflows/ci.yml          # GitHub Actions CI/CD
└── README.md                         # Project documentation
```

### REPRESENTATIVE REQUEST FLOWS

**Flow 1: Brand creation and content factory activation**
```
POST /api/v1/brands → backend/app/api/v1/brands.py:create_brand()
  → require_role("manager") via deps.py
  → BrandCreate Pydantic schema validation
  → brand_service.create_brand() → INSERT into PostgreSQL brands table

POST /api/v1/brands/{id}/activate → brands.py:activate_content_factory()
  → rate limited 5/min → publishes NATS message "markai.activate"
  → agents/worker.py receives → dispatches research → strategy → planning → content
  → each workflow writes to PostgreSQL via agents/shared/tools/database.py
  → notifications sent via SSE + Teams webhook
```

**Flow 2: Content approval and publishing**
```
POST /api/v1/approvals → approvals.py:create_approval() → Approval(status="pending")
PUT /api/v1/approvals/{id} → update status to "approved" → transition calendar_item
Scheduler publish_checker (every 15min) → finds approved items → publish_service.publish_to_n8n()
  → n8n publishes to social platforms → calls back POST /api/v1/webhooks/publish-result
  → updates calendar_item status to "published"
```

**Flow 3: Analytics engagement pull**
```
Scheduler engagement_puller (every 6h) → queries published items with platform_post_id
  → calls social platform APIs → stores EngagementMetric records
GET /api/v1/analytics/engagement/timeseries → raw SQL grouping by date
  → rendered by EngagementChartInner.tsx (Recharts)
```

**Flow 4: Business Central product sync**
```
Scheduler bc_sync (every 6h) → fabric_service.query_bc_table() via pyodbc
  → queries Fabric SQL endpoint → upserts Product records (brand_id + bc_item_no)
```

### KEY INTEGRATION POINTS

| External System | Integration File(s) | Protocol |
|----------------|---------------------|----------|
| Microsoft Entra ID | backend/app/auth/entra.py, backend/app/deps.py | OAuth2 + MS Graph API |
| Microsoft Fabric | backend/app/services/fabric_service.py, agents/shared/tools/fabric.py | pyodbc MSSQL / REST |
| OpenAI | via LiteLLM proxy | HTTP → LiteLLM → OpenAI API |
| Google Gemini | backend/app/services/gemini_service.py, agents/shared/tools/web_search.py | google-genai SDK |
| Meta (FB/Instagram) | via n8n + agents/shared/tools/social.py | Graph API |
| LinkedIn | via n8n + agents/shared/tools/social.py | REST API |
| YouTube | via n8n | OAuth2 |
| TikTok | via n8n | REST API |
| X/Twitter | via n8n | OAuth 1.0a |
| Microsoft Teams | notifications/app/teams.py | Incoming Webhook |

---

## 4. FILE-BY-FILE AUDIT DIRECTIVES

### GROUP 1: HIGH-PRIORITY FILES

**FILE: backend/app/main.py (166 lines)**
PRIORITY: HIGH
AUDIT FOR:
- CORS config lines ~98-107: `allow_methods=["*"]`, `allow_headers=["*"]` — overly permissive
- Missing security headers: X-Content-Type-Options, X-Frame-Options, HSTS, CSP
- Global exception handler lines ~117-135: keyword-based log sanitization — misses patterns like `sk-proj-...`, `AIza...`
- Rate limiter line ~86: `default_limits=["120/minute"]` — no per-endpoint differentiation
- Health endpoint line ~150: unauthenticated `/health`
RELATED FILES: backend/app/config.py, backend/app/deps.py

**FILE: backend/app/config.py (167 lines)**
PRIORITY: HIGH
AUDIT FOR:
- Production credential validation lines ~136-166: only checks SECRET_KEY, POSTGRES_PASSWORD, MINIO_SECRET_KEY — MISSING OPENAI_API_KEY, AZURE_AD_CLIENT_SECRET, FABRIC_CLIENT_SECRET, LITELLM_MASTER_KEY, N8N_WEBHOOK_SECRET, GEMINI_API_KEY
- FRONTEND_URL empty default — must be set for CORS
- VALKEY_PASSWORD empty default — cache without authentication

**FILE: backend/app/deps.py (120 lines)**
PRIORITY: HIGH
AUDIT FOR:
- JWT signature validation against Entra ID JWKS endpoint
- Token expiration (`exp`) and audience (`aud`) claim checks
- User `is_active` flag verification
- Auto-creation of users from valid Entra tokens — potential unauthorized access
- Security group auto-promotion to admin

**FILE: backend/app/auth/entra.py**
PRIORITY: HIGH
AUDIT FOR:
- OData injection in Graph API user search (lines ~115-146): `safe_q` escaping adequacy
- Graph API token caching (lines ~40-112): non-invalidatable cached tokens
- JWKS key caching and rotation handling
- TLS verification on httpx calls

**FILE: backend/app/api/v1/brands.py (629 lines)**
PRIORITY: HIGH
AUDIT FOR:
- Logo upload: 5MB limit, content type validation for executable prevention
- PUBLIC logo serving endpoint (no auth) — intentional?
- `activate_content_factory()`: rate limit 5/min
- Brand deletion: HARD DELETE with cascade behavior
- `complete_onboarding()`: required field validation

**FILE: backend/app/api/v1/products.py (472 lines)**
PRIORITY: HIGH
AUDIT FOR:
- Product image upload: 20/min rate limit, 5MB max, content type validation
- `fetch_product_images()`: Gemini call — prompt injection from product descriptions
- `batch_fetch_product_images()`: unbounded batch size
- `set_primary_product_image()`: no bounds checking on image_index
- `delete_product_image()`: MinIO deletion with error swallowing

**FILE: backend/app/api/v1/users.py (299 lines)**
PRIORITY: HIGH
AUDIT FOR:
- `search_entra_users()`: OData injection protection
- `grant_access()`: privilege escalation prevention
- PUT/PATCH duplicate logic
- Uniqueness constraints on email/entra_object_id

**FILE: backend/app/api/v1/webhooks.py**
PRIORITY: HIGH
AUDIT FOR:
- Plain string comparison instead of HMAC-SHA256 signature verification
- No replay attack protection (no timestamp)
- Webhook secret in HTTP header (loggable by proxies)

**FILE: backend/app/api/v1/settings.py**
PRIORITY: HIGH
AUDIT FOR:
- Raw SQL via `text()` for app_settings (no SQLAlchemy model)
- GET returns ALL settings — potential secret exposure
- PUT validates known keys — is the list complete?

**FILE: backend/app/api/v1/system.py (391 lines)**
PRIORITY: HIGH
AUDIT FOR:
- `system_queues()`: NATS info leakage
- `system_services()`: internal network topology exposure
- `trigger_job()`: arbitrary code trigger potential

**FILE: backend/app/api/v1/analytics.py**
PRIORITY: HIGH
AUDIT FOR:
- Raw SQL with bound parameters — verify all properly parameterized
- `days` parameter: unbounded — expensive query potential
- `get_brand_metrics()`: no pagination

**FILE: agents/worker.py (877 lines)**
PRIORITY: HIGH
AUDIT FOR:
- NATS message acknowledgement patterns
- Unknown workflow type rejection
- Failed workflow database consistency
- Concurrent run prevention via unique index

**FILE: agents/shared/llm.py**
PRIORITY: HIGH
AUDIT FOR:
- LiteLLM timeout/retry/fallback behavior
- Token counting accuracy
- User input sanitization before system prompts

**FILE: agents/shared/tools/fabric.py**
PRIORITY: HIGH
AUDIT FOR:
- SQL parameterization (no string interpolation)
- pyodbc connection cleanup
- Credential exposure in logs
- BC table name whitelist validation

**FILE: backend/app/services/minio_service.py**
PRIORITY: HIGH
AUDIT FOR:
- `secure=False` — plaintext credentials
- Path traversal in file operations
- Bucket policy (public access?)

**FILE: .env**
PRIORITY: CRITICAL
AUDIT FOR:
- LIVE production secrets committed to git
- ALL secrets must be rotated
- Git history cleanup needed

### GROUP 2: STANDARD SOURCE FILES

All backend models (14 files in `backend/app/models/`), schemas (14 files in `backend/app/schemas/`), services (17 files in `backend/app/services/`), and scheduler jobs (5 files in `backend/app/scheduler/`) — verify consistency, error handling, and security.

All agent shared modules (6 files in `agents/shared/`) and tools (8 files in `agents/shared/tools/`) — verify sanitization, error handling, credential management.

All agent workflows (7 workflows, each with graph.py, nodes.py, state.py) — verify LLM output parsing, state management, error recovery.

All browser-worker modules (5 files in `browser-worker/app/`) — verify SSRF protection, URL validation, authentication.

All notifications modules (5 files in `notifications/app/`) — verify SSE auth, Teams payload safety.

All frontend pages (22 in `frontend/src/app/`), components (50 in `frontend/src/components/`), and utilities (4 in `frontend/src/lib/`) — verify role enforcement, error handling, XSS prevention, accessibility.

**NOTE:** `backend/app/models/prompt_version.py` line 35: Numeric(7,4) vs init.sql NUMERIC(5,4) — precision mismatch.
**NOTE:** `backend/app/services/content_service.py`: `list_content()` missing eager load for calendar_item — N+1 risk.
**NOTE:** `backend/app/api/v1/calendar.py` and `users.py`: PUT/PATCH duplicate logic.
**NOTE:** `backend/app/api/v1/approvals.py`: `status` vs `status_filter` inconsistency; POST `/decide` duplicates PUT.
**NOTE:** `backend/app/api/v1/providers.py`: `get_active_models()` is PUBLIC (no auth) — used by agents internally.
**NOTE:** `browser-worker/app/config.py`: `MINIO_SECURE` defaults to False.

### GROUP 3: CONFIGURATION FILES

**docker-compose.yml (473 lines)** — Verify resource limits, healthchecks, network isolation, volume persistence, secret handling.
**docker-compose.override.yml (91 lines)** — Verify host bindings on 127.0.0.1 only, dev-only features.
**docker-compose.vps.yml (74 lines)** — Verify Traefik labels, TLS, external network access.
**.github/workflows/ci.yml** — Verify versions match Dockerfiles, missing stages (security, coverage, Docker build).
**litellm/config.yaml** — Verify model routing, fallbacks, rate limits.
**.env.example** — Verify completeness vs code references.
**frontend/tsconfig.json** — Verify strict mode, path aliases.
**frontend/next.config.ts** — Verify standalone output, image domains, security headers.
**All observability configs** — Verify scrape targets, retention, alerts.

### GROUP 4: TEST FILES

| File | Covers | Missing |
|------|--------|---------|
| backend/tests/conftest.py (20 lines) | Test env setup | DB fixtures, API client, mocks |
| backend/tests/test_api_health.py (27 lines) | GET /health, app title/version | Error scenarios, middleware |
| backend/tests/test_auth_permissions.py (42 lines) | 7 RBAC hierarchy tests | Integration with users/API |
| backend/tests/test_utils.py (29 lines) | ROLES dict validation | Actual utility functions |
| agents/tests/test_sanitize.py (73 lines) | 12 injection sanitization tests | Unicode, more bypass patterns |
| agents/tests/test_llm_parsing.py (65 lines) | 12 LLM parsing tests | Trailing text, malformed |

### GROUP 5: INFRASTRUCTURE FILES

5 Dockerfiles — Verify multi-stage, non-root, healthchecks, no secrets in build args.
5 .dockerignore files — Verify .env and sensitive files excluded.
`scripts/vps-redeploy.sh` (105 lines) — DESTRUCTIVE volume wipe without backup.
`scripts/seed-dev.py` (217 lines) — Dev data seeding.

### GROUP 6: DATA FILES

**db/init.sql (517 lines)** — 19 tables, verify match with SQLAlchemy models.
**backend/alembic/versions/ (EMPTY)** — No migrations committed — significant production risk.

---

## 5. DEPENDENCY & VERSION AUDIT DIRECTIVES

VERIFY EACH — web search individually for latest stable version:

### CRITICAL (10)
1. next ^16.2.1 — `"next.js latest stable version 2026"`
2. react ^19.2.4 — `"react latest stable version 2026"`
3. fastapi >=0.135 — `"fastapi latest stable version 2026"`
4. sqlalchemy >=2.0.48 — `"sqlalchemy latest stable version 2026"`
5. pydantic >=2.12 — `"pydantic latest stable version 2026"`
6. langgraph >=1.0,<2.0 — `"langgraph latest stable version 2026"`
7. langchain-core >=1.0,<2.0 — `"langchain-core latest stable version 2026"`
8. langchain-openai >=1.0,<2.0 — `"langchain-openai latest stable version 2026"`
9. next-auth ^4.24.11 — `"next-auth latest stable version 2026"` (Auth.js v5?)
10. litellm >=1.60 (Docker: v1.82.3) — `"litellm latest stable version 2026"`

### IMPORTANT (24)
11-34. asyncpg, alembic, httpx, nats-py, minio, qdrant-client, playwright, google-genai, Pillow, apscheduler, zustand, recharts, tailwindcss, typescript, PyJWT, bcrypt, tenacity (NOTE: >=8.2 in backend vs >=9.0 in agents), slowapi, beautifulsoup4, sse-starlette, valkey, redis, pyodbc, numpy

### DEV (4)
35-38. eslint, eslint-config-next, @tailwindcss/postcss, postcss

### RADIX UI (10)
39-48. All @radix-ui/* packages

### INFRASTRUCTURE (13)
49-61. PostgreSQL 16, Qdrant v1.17.0, MinIO 2025-01-20, Valkey 9.0.3, NATS 2.12.5, LiteLLM v1.82.3, n8n 1.82.1, Traefik v3.6, Grafana 12.4.1, Prometheus v3.10.0, Loki 3.6.7, Promtail 3.6.7, OTel Collector 0.147.0

AFTER ALL VERSION CHECKS:
```bash
cd frontend && npm audit
cd backend && pip install pip-audit && pip-audit
cd agents && pip install pip-audit && pip-audit
```

---

## 6. AI/ML AUDIT DIRECTIVES

### AI MODELS IN USE

1. **LLM via LiteLLM Proxy** — `litellm/config.yaml` — OpenAI + Gemini models
   - VERIFY: Are configured models still current? Search latest model lists.

2. **Google Gemini Direct** — `backend/app/services/gemini_service.py`, `agents/shared/tools/web_search.py`
   - SDK: google-genai>=1.5 — product image analysis (vision), web search grounding
   - VERIFY: SDK version current? Model strings still available?

3. **LangChain/LangGraph** — `agents/workflows/` — 7 workflow pipelines
   - VERIFY: Breaking changes in LangGraph >=1.0?

### AI MODEL MANAGEMENT SYSTEM

- `ai_model_categories` table: text, text-fast, image, embedding, vision
- `ai_models` table: discovered models with capabilities
- `ai_model_selections` table: active model per category
- Discovery: `backend/app/scheduler/model_discovery.py`
- VERIFY: Discovery doesn't overwrite admin selections

### INTEGRATION QUALITY — check these files:

- `agents/shared/llm.py`: Error handling? Retry? Timeout? Token limits? Cost tracking?
- `agents/shared/sanitize.py`: Injection patterns comprehensive? ("ignore all previous", "system:", [INST] tags — more?)
- `agents/workflows/content/nodes.py`: Malformed LLM output handling? Retry on parse failure?
- `backend/app/services/gemini_service.py`: API errors? Rate limiting? Timeout?
- `backend/app/api/v1/intelligence.py`: User input sanitized before LLM? Rate limit 10/min sufficient?

### PROMPT REVIEW

- All prompts in `prompt_versions` table: injection vulnerabilities, template variable risks
- All prompt construction in `agents/workflows/*/nodes.py`: role separation, input sanitization, output validation
- `backend/app/services/gemini_service.py`: system prompt safety

---

## 7. SECURITY AUDIT DIRECTIVES

### CRITICAL: PRODUCTION SECRETS IN GIT

`.env` committed with LIVE secrets: Azure AD, OpenAI (sk-proj-...), Gemini (AIza...), LiteLLM, PostgreSQL, MinIO, n8n, Fabric credentials, tenant/client IDs, production domains.

AUDIT: Verify rotation needed. Verify .gitignore. Verify git history cleanup. Recommend `git filter-repo --path .env --invert-paths`.

### AUTHENTICATION (Entra ID SSO + JWT)

Auth chain: NextAuth → Azure AD → JWT → backend deps.py:get_current_user() → JWKS verification → user lookup/auto-create → role check

**Unprotected routes:** GET /health, GET /brands/{id}/logos/{label}, GET /providers/active, GET /system/queues (VERIFY), GET /providers/categories (VERIFY)

**Verify:** JWKS rotation, exp/aud/iss claim validation, is_active check, auto-create security, security group check frequency

### KNOWN SECURITY CONCERNS (11)

| ID | Severity | Location | Issue |
|----|----------|----------|-------|
| SEC-01 | CRITICAL | .env | Production secrets committed |
| SEC-02 | HIGH | main.py:98-107 | CORS allow_methods/headers=["*"] |
| SEC-03 | HIGH | main.py | Missing security headers |
| SEC-04 | HIGH | minio_service.py | secure=False (plaintext creds) |
| SEC-05 | MEDIUM | config.py:136-166 | Incomplete credential validation |
| SEC-06 | MEDIUM | entra.py:115-146 | OData injection in Graph search |
| SEC-07 | MEDIUM | webhooks.py | No HMAC, no replay protection |
| SEC-08 | MEDIUM | main.py:86 | Undifferentiated rate limiting |
| SEC-09 | MEDIUM | entra.py:40-112 | Non-invalidatable token cache |
| SEC-10 | LOW | main.py:117-135 | Weak log sanitization patterns |
| SEC-11 | LOW | browser-worker/config.py | MINIO_SECURE defaults False |

### INPUT VALIDATION

- Library: Pydantic v2 (schemas in `backend/app/schemas/`)
- Missing: analytics `days` unbounded, products `image_index` unchecked, approvals param inconsistency, brands competitor URL unvalidated, skip/limit negative values

### ENVIRONMENT & SECRETS

- 27+ secrets referenced across 4 services
- .env in .gitignore: Yes (but already committed)
- No hardcoded secrets in source code
- Insecure defaults: SECRET_KEY="change-me...", POSTGRES_PASSWORD="change-me", MINIO_SECRET_KEY="change-me", VALKEY_PASSWORD="" (empty)

---

## 8. DATABASE & DATA LAYER AUDIT DIRECTIVES

**DATABASE:** PostgreSQL 16 via SQLAlchemy 2.0+ (async asyncpg)
**SCHEMA FILE:** db/init.sql (517 lines)
**CONNECTION POOL:** 20 + 10 overflow, pre-ping enabled

### 19 TABLES

| Table | Fields | Key Relationships |
|-------|--------|-------------------|
| users | 10 | → notifications (1:N) |
| notifications | 12 | → user (N:1, CASCADE) |
| audit_log | 10 | → user (N:1, NO CASCADE — BLOCKS DELETE) |
| scheduled_job_log | 10 | standalone |
| brands | 20 | → products, campaigns, calendar_items, competitors, agent_runs (1:N) |
| products | 29 | → brand (N:1, CASCADE) |
| campaigns | 14 | → brand (N:1, CASCADE), → calendar_items (1:N) |
| calendar_items | 22 | → brand, campaign (N:1), → content, approvals, engagement_metrics (1:N) |
| content | 22 | → calendar_item, brand (N:1), → adaptations, approvals, engagement_metrics (1:N) |
| approvals | 9 | → content, calendar_item (N:1, CASCADE), → reviewer (N:1) |
| prompt_versions | 12 | → agent_runs (1:N) |
| agent_runs | 16 | → brand, prompt_version (N:1), partial unique WHERE status='running' |
| engagement_metrics | 17 | → content, calendar_item, brand (N:1, CASCADE) |
| adaptations | 13 | → source_content (N:1, CASCADE) |
| competitors | 10 | → brand (N:1, CASCADE) |
| ai_model_categories | 4 | → models, selections (1:N) |
| ai_models | 7 | → category (N:1), → selections (1:N) |
| ai_model_selections | 6 | → category, model (N:1) |
| app_settings | 4 | standalone (NO SQLAlchemy model!) |

### KNOWN ISSUES

1. **Numeric mismatch:** prompt_versions.performance_score — init.sql NUMERIC(5,4) vs model Numeric(7,4)
2. **No ORM model:** app_settings managed via raw SQL
3. **Missing back_populates:** User↔Approvals, User↔PromptVersions, Brand↔Content, Brand↔EngagementMetrics
4. **audit_log.user_id:** No ON DELETE (defaults RESTRICT — blocks user deletion)
5. **Channel type inconsistency:** engagement_metrics.channel VARCHAR(255) vs others VARCHAR(50)
6. **N+1 risks:** content_service.list_content() missing selectinload(calendar_item), product queries no selectinload(brand)

### RAW SQL USAGE (all parameterized — verify)

analytics.py, dashboard.py, settings.py, system.py, morning_jobs.py, scheduler/__init__.py

### MIGRATIONS: EMPTY — no versions committed. Schema untracked.

---

## 9. API ENDPOINT AUDIT DIRECTIVES

### 113 ENDPOINTS — COMPLETE INVENTORY

(See full table in Section 9 of the generated document. Key highlights:)

- **111 backend endpoints** across 19 route modules
- **1 frontend API route** (NextAuth handler)
- **1 health endpoint** (unauthenticated)
- **3 public endpoints:** /health, /brands/{id}/logos/{label}, /providers/active
- **2 possibly missing auth:** /system/queues, /providers/categories
- **Rate-limited endpoints:** brands/activate (5/min), intelligence/generate-fields (10/min), intelligence/rewrite-field (10/min), products/upload-image (20/min)
- **Webhook:** /webhooks/publish-result (header secret only, no HMAC)
- **Duplicate endpoints:** calendar PUT/PATCH, users PUT/PATCH, approvals PUT/POST-decide

FOR EACH ENDPOINT VERIFY: auth, authz, input validation, response format, error handling, rate limiting, HTTP status codes, pagination

---

## 10. FRONTEND & UI AUDIT DIRECTIVES

**22 pages**, **50 components**, **Tailwind CSS v4**, **Radix UI**, **Zustand state**, **NextAuth Azure AD**

### KEY CONCERNS
1. No pagination component — client-side slice(0, 10)
2. No keyboard shortcuts
3. Custom DOM events for brand switching (brittle)
4. No test framework installed
5. Touch targets some at 40px (below 44px minimum)
6. All data fetching via useEffect + custom ApiClient (no SWR/React Query)

VERIFY: Role enforcement on all pages, error boundaries, responsive design, accessibility, XSS prevention in rendered content

---

## 11. TESTING AUDIT DIRECTIVES

**Framework:** pytest | **Coverage:** ~1-2% | **Frontend tests:** ZERO

### 6 TEST FILES (256 lines total)

All untested: 19 API route modules, 17 services, 14 models, 7 workflows, 8 agent tools, browser-worker, notifications, ALL frontend components

### MISSING INFRASTRUCTURE
- No pytest-cov/coverage.py
- No test database fixtures
- No API test client
- No frontend test framework
- No CI coverage threshold
- No pre-commit hooks

---

## 12. INFRASTRUCTURE & DEVOPS AUDIT DIRECTIVES

### DOCKER: 5 Dockerfiles (all multi-stage, non-root, healthchecked)
### CI/CD: GitHub Actions — 4 jobs (lint + test only)
### MISSING: Security scanning, dependency scanning, coverage reporting, Docker build testing, automated deployment

### DEPLOYMENT CONCERN: `scripts/vps-redeploy.sh` wipes PostgreSQL + Qdrant volumes on every deploy without backup

### ENV MANAGEMENT: 3 insecure defaults (SECRET_KEY, POSTGRES_PASSWORD, MINIO_SECRET_KEY), VALKEY_PASSWORD empty

---

## 13. PERFORMANCE AUDIT DIRECTIVES

### DATABASE
- content_service.list_content() missing selectinload → N+1
- analytics.py unbounded days parameter
- competitors list no pagination
- Product/Adaptation queries no eager loading

### BACKEND
- Hard-coded 5-min cache TTLs (not configurable)
- batch_fetch_product_images sequential (no concurrency)
- SSE notification polling (10s) vs proper pub/sub
- NATS fire-and-forget without delivery confirmation

### FRONTEND
- No server-side pagination (max 200 client-side)
- Header notification polling 30s (should use SSE)
- recharts large bundle — verify tree-shaking
- No React.memo on list items

---

## 14. CODE QUALITY & PATTERN AUDIT DIRECTIVES

### CONVENTIONS: snake_case Python, camelCase TS, PascalCase components, Pydantic schemas, Depends() auth, async SQLAlchemy

### DEVIATIONS
- settings.py uses raw SQL (others use ORM)
- approvals.py has status/status_filter inconsistency
- calendar.py and users.py: PUT/PATCH duplicate
- tenacity version mismatch across services (>=8.2 vs >=9.0)

### DEAD CODE: bcrypt (unused — auth is Entra ID SSO)
### COMPLEXITY: worker.py (877 lines), brands.py (629 lines), products.py (472 lines)
### DUPLICATION: PUT/PATCH duplicates, raw SQL for app_settings in 3 files, Pydantic DB config in 4 services

---

## 15. KNOWN ISSUES PRE-LOADED

### CRITICAL (1)
- **[PRE-001]** .env — Production secrets committed to git

### HIGH (8)
- **[PRE-002]** main.py:98-107 — CORS allow_methods/headers=["*"]
- **[PRE-003]** main.py — Missing security headers
- **[PRE-004]** minio_service.py + browser-worker/config.py — secure=False
- **[PRE-005]** config.py:136-166 — Incomplete credential validation
- **[PRE-006]** alembic/versions/ — Empty, no migrations
- **[PRE-007]** vps-redeploy.sh — Destructive volume wipe without backup
- **[PRE-008]** Zero frontend tests
- **[PRE-009]** ~1-2% overall test coverage

### MEDIUM (15)
- **[PRE-010]** entra.py:115-146 — OData injection risk
- **[PRE-011]** webhooks.py — No HMAC, no replay protection
- **[PRE-012]** main.py:86 — Undifferentiated rate limiting
- **[PRE-013]** prompt_version.py:35 — Numeric precision mismatch
- **[PRE-014]** settings.py — No ORM model for app_settings
- **[PRE-015]** content_service.py — Missing eager load (N+1)
- **[PRE-016]** analytics.py — Unbounded days parameter
- **[PRE-017]** calendar.py, users.py — PUT/PATCH duplicates
- **[PRE-018]** approvals.py — Param inconsistency, POST/PUT duplicate
- **[PRE-019]** Missing bidirectional relationships
- **[PRE-020]** tenacity version mismatch across services
- **[PRE-021]** products.py — image_index no bounds check
- **[PRE-022]** entra.py:40-112 — Non-invalidatable token cache
- **[PRE-023]** main.py:117-135 — Weak log sanitization
- **[PRE-024]** init.sql — audit_log user_id no ON DELETE

### LOW (6)
- **[PRE-025]** bcrypt unused dependency
- **[PRE-026]** All deletes are hard deletes
- **[PRE-027]** engagement_metrics.channel VARCHAR(255) vs others VARCHAR(50)
- **[PRE-028]** No pre-commit hooks
- **[PRE-029]** No dependency scanning in CI/CD
- **[PRE-030]** Frontend polling instead of SSE

### TODO/FIXME/HACK: **None found** in any source file.

THE AUDITING AGENT MUST verify each issue and find MORE beyond this list.

---

## 16. CROSS-CUTTING ANALYSIS DIRECTIVES

### DEPENDENCY GRAPH — Trace for circular deps:
- backend/app/main.py → router.py → 19 routes → deps.py → auth/entra.py
- agents/worker.py → nats_consumer.py → 7 workflows → nodes → tools
- frontend layout.tsx → providers → pages → components

### COUPLING HOTSPOTS (if these break, everything breaks):
- backend/app/deps.py — all routes depend on it
- backend/app/models/base.py — all DB access
- agents/shared/config.py — all agent tools/workflows
- frontend/src/lib/api.ts — all pages/components

### AUTH FLOW — Verify each step:
NextAuth → Azure AD → JWT → deps.py → JWKS verify → user lookup/auto-create → is_active → role check
ESPECIALLY: auto-create from any valid token, security group check frequency

### ERROR PROPAGATION — Verify:
DB error → SQLAlchemy → service → route → HTTPException → JSON response
No SQL/connection string leakage, appropriate status codes, frontend error handling

### BUSINESS LOGIC CONSISTENCY — Verify same rules in:
- Content status transitions (backend vs frontend)
- Role hierarchy (permissions.py vs useRequireRole)
- Channel list (DB CHECK vs brands.py vs frontend types)
- Brand activation flow (backend state machine vs frontend UI)

---

## 17. AUDIT EXECUTION RULES

1. **READ-ONLY:** Do not modify any file.
2. **EVERY FILE:** Read every file. Use Section 4 as checklist.
3. **WEB SEARCH:** For every dependency in Section 5, individually search latest stable version.
4. **EVIDENCE:** Every finding: exact file, line(s), code snippet, explanation, recommended fix.
5. **MINIMUM 3 PASSES:** Re-read every file at least 2 more times after initial audit.
6. **NO HAND-WAVING:** Cite what you verified or cite the specific issue.
7. **PRE-LOADED ISSUES:** Start with Section 15. Then find MORE.
8. **SEVERITY:** CRITICAL / HIGH / MEDIUM / LOW / INFO (definitions in Section 17 of the generator prompt).

---

## 18. OUTPUT REQUIREMENTS

Produce: `./CODEBASE_AUDIT_REPORT.md`

Contents:
1. Executive Summary (findings by severity, overall grade, top 5 critical)
2. Dependency Audit Table (current vs latest, advisories)
3. AI/ML Model Audit (models, SDKs, integration quality)
4. All Findings by severity (ID, file, lines, snippet, description, impact, fix, effort)
5. Pre-loaded Issues Verification (each from Section 15)
6. Security Assessment (A-F)
7. Performance Assessment (A-F)
8. Code Quality Assessment (A-F)
9. Testing Assessment (A-F)
10. Phased Remediation Plan (A-K: critical security → critical bugs → dep updates → high fixes → AI updates → medium fixes → testing → infra → low/polish → docs)
11. File-by-File Index (every file, finding count)
12. Metrics Dashboard (total files, findings, compliance rates)
