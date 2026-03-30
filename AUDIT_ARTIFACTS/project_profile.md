# MARKAI Project Profile

Generated: 2026-03-30

## Project Type

**Monorepo** -- a single repository containing multiple services, all orchestrated via Docker Compose.

## Services

| Service | Directory | Language | Framework | Description |
|---------|-----------|----------|-----------|-------------|
| **Backend** | `backend/` | Python 3.12+ | FastAPI + SQLAlchemy + Alembic | REST API, scheduler, business logic |
| **Frontend** | `frontend/` | TypeScript | Next.js 16 + React 19 + Tailwind CSS 4 | Dashboard UI (App Router) |
| **Agents** | `agents/` | Python 3.12+ | LangGraph + LangChain | AI workflow workers (research, strategy, planning, content, evaluation, adaptation, product_intel) |
| **Browser Worker** | `browser-worker/` | Python 3.12+ | FastAPI + Playwright | Headless browser for screenshots, scraping, product image capture |
| **Notifications** | `notifications/` | Python 3.12+ | FastAPI + SSE-Starlette | Real-time notification delivery (SSE + Teams webhooks) |

## Infrastructure Services (via Docker Compose)

| Service | Image | Purpose |
|---------|-------|---------|
| PostgreSQL 16 | `postgres:16-alpine` | Primary relational database |
| Qdrant v1.17 | `qdrant/qdrant:v1.17.0` | Vector database for embeddings |
| MinIO | `minio/minio` | S3-compatible object storage (images, assets) |
| Valkey 9.0 | `valkey/valkey:9.0.3-alpine` | Redis-compatible cache |
| NATS 2.12 (JetStream) | `nats:2.12.5-alpine` | Message broker for async workflows |
| LiteLLM | `ghcr.io/berriai/litellm` | LLM gateway/proxy (routes to OpenAI, etc.) |
| n8n 1.82 | `docker.n8n.io/n8nio/n8n` | Workflow automation (publishing) |
| Traefik v3.6 | `traefik:v3.6` | Reverse proxy / TLS termination |
| Grafana 12.4 | `grafana/grafana:12.4.1` | Observability dashboards |
| Prometheus v3.10 | `prom/prometheus:v3.10.0` | Metrics collection |
| Loki 3.6 | `grafana/loki:3.6.7` | Log aggregation |
| OTel Collector 0.147 | `otel/opentelemetry-collector-contrib` | OpenTelemetry trace/metric pipeline |

**Total: 5 custom services + 12 infrastructure services = 17 containers**

## Languages

| Language | Usage |
|----------|-------|
| **Python** | Backend API, Agents, Browser Worker, Notifications, utility scripts |
| **TypeScript / TSX** | Frontend (Next.js App Router) |
| **SQL** | Database schema init (`db/init.sql`) + Alembic migrations |
| **YAML** | Docker Compose, LiteLLM config, observability configs, eval configs |

## Frameworks and Key Libraries

### Python (Backend)
- FastAPI (REST API framework)
- SQLAlchemy 2.0+ (async ORM)
- Alembic (database migrations)
- Pydantic 2.12+ / Pydantic Settings
- APScheduler (scheduled jobs)
- NATS.py (message broker client)
- MinIO SDK (object storage)
- Qdrant Client (vector DB)
- LiteLLM (LLM gateway client)
- Google GenAI SDK (Gemini integration)
- Pillow (image processing)
- PyJWT (authentication)
- HTTPX (async HTTP client)
- PyODBC (Business Central / SQL Server connector)
- OpenTelemetry (tracing/metrics)

### Python (Agents)
- LangGraph (agentic workflow orchestration)
- LangChain Core + LangChain OpenAI
- LiteLLM (model routing)
- Google GenAI (Gemini image generation)
- Playwright (browser automation)
- NumPy, Pillow (image processing)
- Tenacity (retry logic)

### Python (Browser Worker)
- FastAPI + Playwright
- BeautifulSoup4 (HTML parsing)
- MinIO, Pillow

### Python (Notifications)
- FastAPI + SSE-Starlette (Server-Sent Events)
- Valkey/Redis client
- SQLAlchemy (async)

### TypeScript (Frontend)
- Next.js 16 (App Router)
- React 19
- Tailwind CSS 4
- Radix UI (avatar, dialog, dropdown, label, select, separator, switch, tabs, tooltip)
- dnd-kit (drag & drop for Kanban)
- Zustand (state management)
- NextAuth v4 (authentication)
- Recharts (charting)
- Lucide React (icons)
- Sonner (toast notifications)
- React Markdown (content rendering)

## Package Managers and Build Tools

| Tool | Where | Purpose |
|------|-------|---------|
| **pip / setuptools / hatchling** | All Python services | Python dependency management + build |
| **npm** | `frontend/` | Node.js package management |
| **Docker / Docker Compose** | Root | Container orchestration |
| **Alembic** | `backend/` | Database schema migrations |
| **ESLint** | `frontend/` | TypeScript/React linting |
| **Ruff** | Python services (dev dep) | Python linting/formatting |
| **pytest** | Python services (dev dep) | Testing |
| **Promptfoo** | `eval/` | LLM prompt evaluation framework |

## Runtimes

- **Python 3.12+** (all backend services)
- **Node.js** (frontend, version determined by Next.js 16 requirements -- likely Node 20+)
- **Docker Engine** (container runtime)

## Authentication

- **Frontend**: NextAuth v4 with Microsoft Entra ID (Azure AD) provider
- **Backend**: PyJWT with Entra ID token validation
- **Inter-service**: Shared .env secrets

## Deployment

- **Local dev**: `docker compose up -d` (uses `docker-compose.override.yml` for port bindings)
- **VPS production**: `docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d` (Traefik with TLS)
- All services on a single `markai-net` bridge network

## AI / ML Pipeline

1. **LiteLLM proxy** routes all LLM calls (GPT-5.4, GPT-5.4-mini, text-embedding-3-small, GPT-Image-1/1.5, Sora-2)
2. **LangGraph agents** execute 7 workflow types: research, strategy, planning, content, evaluation, adaptation, product_intel
3. **NATS JetStream** provides async job dispatch between backend and agents
4. **Qdrant** stores vector embeddings for brand knowledge and content similarity
5. **Google Gemini** used for image generation/editing alongside OpenAI models
6. **Promptfoo** for LLM output evaluation and quality testing
