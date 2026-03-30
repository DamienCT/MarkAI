# MARKAI Environment Profile

*Generated: 2026-03-30*

---

## 1. Docker Runtime Environments

### 1.1 Dockerfiles

| Service | Dockerfile | Base Image | Runtime | Port |
|---------|-----------|------------|---------|------|
| **backend** | `backend/Dockerfile` | `python:3.13-slim` (multi-stage) | Uvicorn (FastAPI) | 8000 |
| **frontend** | `frontend/Dockerfile` | `node:22-alpine` (multi-stage) | Node.js (Next.js standalone) | 3000 |
| **agents** | `agents/Dockerfile` | `python:3.13-slim` (multi-stage) | Python module (`python -m worker`) | N/A (no HTTP) |
| **browser-worker** | `browser-worker/Dockerfile` | `python:3.13-slim` (multi-stage) | Uvicorn (FastAPI) + Playwright Chromium | 8001 |
| **notifications** | `notifications/Dockerfile` | `python:3.13-slim` (multi-stage) | Uvicorn (FastAPI) | 8002 |

**Common build-time dependencies:**
- `backend`, `agents`: libpq-dev, unixodbc-dev, msodbcsql17 (ODBC driver for Microsoft SQL / Fabric)
- `agents`: Playwright Chromium + imagemagick + fonts-dejavu-core
- `browser-worker`: Playwright Chromium
- All Python services use non-root `appuser` (UID 1001)
- Frontend uses non-root `nextjs` (UID 1001)

### 1.2 Docker Compose Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base services definition. No host port bindings on internal services. |
| `docker-compose.override.yml` | Local development overrides. Adds host port bindings, hot-reload volumes, `MARKAI_ENV=development`. Auto-loaded by `docker compose up`. |
| `docker-compose.vps.yml` | VPS production overlay. Disables bundled Traefik & n8n (uses VPS-level ones). Adds Traefik labels for auto-discovery. Connects to external `n8n_default` network. Observability stack gated behind `--profile observability`. |

### 1.3 All Docker Compose Services (17 total)

| Service | Image/Build | Type | Resource Limits |
|---------|------------|------|-----------------|
| `traefik` | `traefik:v3.6` | Reverse proxy | - |
| `postgres` | `postgres:16-alpine` | Database | 1G memory |
| `qdrant` | `qdrant/qdrant:v1.17.0` | Vector DB | - |
| `minio` | `minio/minio:RELEASE.2025-01-20T14-49-07Z` | Object storage | - |
| `valkey` | `valkey/valkey:9.0.3-alpine` | Cache (Redis-compatible) | - |
| `nats` | `nats:2.12.5-alpine` | Message broker (JetStream) | - |
| `litellm` | `ghcr.io/berriai/litellm:main-latest` | LLM gateway | 1G memory |
| `n8n` | `docker.n8n.io/n8nio/n8n:1.82.1` | Workflow automation | - |
| `backend` | Build: `./backend` | FastAPI app | 1G memory |
| `frontend` | Build: `./frontend` | Next.js app | 512M memory |
| `agents` | Build: `./agents` | LangGraph workers | 2G memory |
| `browser-worker` | Build: `./browser-worker` | Playwright scraper | - |
| `notifications` | Build: `./notifications` | SSE + Teams webhooks | - |
| `grafana` | `grafana/grafana:12.4.1` | Dashboards | - |
| `prometheus` | `prom/prometheus:v3.10.0` | Metrics collection | - |
| `loki` | `grafana/loki:3.6.7` | Log aggregation | - |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.147.0` | Telemetry pipeline | - |

---

## 2. CI/CD Configuration

**No CI/CD pipelines found.** There is no `.github/workflows/` directory at the project root. No GitHub Actions, GitLab CI, or other CI/CD config files exist.

---

## 3. Environment Variable Files

### 3.1 `.env.example` (development template)

| Variable | Default / Description |
|----------|----------------------|
| `MARKAI_ENV` | `development` |
| `MARKAI_DOMAIN` | `markai.example.com` |
| `SECRET_KEY` | Placeholder |
| **Microsoft Entra ID (SSO)** | |
| `AZURE_AD_TENANT_ID` | Placeholder |
| `AZURE_AD_CLIENT_ID` | Placeholder |
| `AZURE_AD_CLIENT_SECRET` | Placeholder |
| `NEXTAUTH_URL` | `https://markai.example.com` |
| `NEXTAUTH_SECRET` | Placeholder |
| `ADMIN_SECURITY_GROUP_ID` | Placeholder |
| **Microsoft Fabric / Power BI** | |
| `FABRIC_TENANT_ID` | Placeholder |
| `FABRIC_CLIENT_ID` | Placeholder |
| `FABRIC_CLIENT_SECRET` | Placeholder |
| `FABRIC_SQL_ENDPOINT` | Placeholder |
| `FABRIC_LAKEHOUSE_NAME` | `lh_bronze` |
| **Business Central Tables** | |
| `BC_TABLE_ITEMS` | `itemmodule_item` |
| `BC_TABLE_ITEM_CATEGORIES` | `itemmodule_itemcategory` |
| `BC_TABLE_VENDORS` | `vendormodule_vendor` |
| `BC_TABLE_ITEM_LEDGER_ENTRIES` | `itemmodule_itemledgerentry` |
| **AI API Keys** | |
| `OPENAI_API_KEY` | Placeholder |
| **LiteLLM** | |
| `LITELLM_BASE_URL` | `http://litellm:4000` |
| `LITELLM_MASTER_KEY` | Placeholder |
| **PostgreSQL** | |
| `POSTGRES_HOST` | `postgres` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `markai` |
| `POSTGRES_USER` | `markai` |
| `POSTGRES_PASSWORD` | Placeholder |
| **Qdrant** | |
| `QDRANT_HOST` | `qdrant` |
| `QDRANT_PORT` | `6333` |
| **MinIO** | |
| `MINIO_ENDPOINT` | `minio:9000` |
| `MINIO_ACCESS_KEY` | `markai-minio` |
| `MINIO_SECRET_KEY` | Placeholder |
| `MINIO_BUCKET` | `markai-assets` |
| **Valkey** | |
| `VALKEY_HOST` | `valkey` |
| `VALKEY_PORT` | `6379` |
| **NATS** | |
| `NATS_URL` | `nats://nats:4222` |
| **Frontend** | |
| `FRONTEND_URL` | `http://localhost:3000` |
| **n8n** | |
| `N8N_BASE_URL` | Placeholder |
| `N8N_WEBHOOK_BASE` | Placeholder |
| `N8N_WEBHOOK_SECRET` | Placeholder |
| **Browser Worker** | |
| `BROWSER_WORKER_URL` | `http://browser-worker:8001` |
| **OpenTelemetry** | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (empty = disabled) |
| **LangSmith** | |
| `LANGCHAIN_TRACING_V2` | `true` |
| `LANGCHAIN_API_KEY` | Placeholder |
| `LANGCHAIN_PROJECT` | `markai` |
| **Notifications** | |
| `TEAMS_WEBHOOK_URL` | Placeholder |
| **Social Platform API Keys** | |
| `META_ACCESS_TOKEN` | Placeholder |
| `META_PAGE_ID` | Placeholder |
| `META_INSTAGRAM_ACCOUNT_ID` | Placeholder |
| `LINKEDIN_ACCESS_TOKEN` | Placeholder |
| `LINKEDIN_ORG_ID` | Placeholder |
| `YOUTUBE_CLIENT_ID` | Placeholder |
| `YOUTUBE_CLIENT_SECRET` | Placeholder |
| `YOUTUBE_REFRESH_TOKEN` | Placeholder |
| `YOUTUBE_CHANNEL_ID` | Placeholder |
| `TIKTOK_CLIENT_KEY` | Placeholder |
| `TIKTOK_CLIENT_SECRET` | Placeholder |
| `TIKTOK_ACCESS_TOKEN` | Placeholder |
| `X_API_KEY` | Placeholder |
| `X_API_SECRET` | Placeholder |
| `X_ACCESS_TOKEN` | Placeholder |
| `X_ACCESS_TOKEN_SECRET` | Placeholder |
| **Scheduler** | |
| `SCHEDULER_TIMEZONE` | `Indian/Mauritius` |
| `MORNING_SCHEDULE_HOUR` | `6` |
| `MORNING_SCHEDULE_MINUTE` | `0` |
| `PUBLISH_CHECK_INTERVAL_MINUTES` | `15` |
| `ENGAGEMENT_PULL_INTERVAL_HOURS` | `6` |
| `BC_SYNC_INTERVAL_HOURS` | `6` |

### 3.2 `.env` (production — CONTAINS REAL SECRETS)

**WARNING: `.env` is committed to git and contains real production secrets.**

| Variable | Status |
|----------|--------|
| `SECRET_KEY` | SECRET_VALUE |
| `AZURE_AD_TENANT_ID` | SECRET_VALUE |
| `AZURE_AD_CLIENT_ID` | SECRET_VALUE |
| `AZURE_AD_CLIENT_SECRET` | SECRET_VALUE |
| `ADMIN_SECURITY_GROUP_ID` | SECRET_VALUE |
| `NEXT_PUBLIC_AZURE_AD_CLIENT_ID` | SECRET_VALUE |
| `NEXTAUTH_SECRET` | SECRET_VALUE |
| `FABRIC_TENANT_ID` | SECRET_VALUE |
| `FABRIC_CLIENT_ID` | SECRET_VALUE |
| `FABRIC_CLIENT_SECRET` | SECRET_VALUE |
| `FABRIC_SQL_ENDPOINT` | SECRET_VALUE |
| `OPENAI_API_KEY` | SECRET_VALUE |
| `GEMINI_API_KEY` | SECRET_VALUE |
| `LITELLM_MASTER_KEY` | SECRET_VALUE |
| `POSTGRES_PASSWORD` | SECRET_VALUE |
| `MINIO_SECRET_KEY` | SECRET_VALUE |
| `N8N_WEBHOOK_SECRET` | SECRET_VALUE |

**Notable differences from `.env.example`:**
- `MARKAI_ENV=production`
- `GEMINI_API_KEY` present (not in `.env.example`)
- Social platform keys (`META_*`, `LINKEDIN_*`, etc.) NOT present (configured per-brand in UI)
- Scheduler env vars NOT present (defaults used from app_settings DB table)
- `LANGCHAIN_TRACING_V2=false` (disabled in production)

### 3.3 `.env.vps.example` (VPS production template)

Same structure as `.env` production, with `[REQUIRED]` and `[CHANGE-ME]` annotations. Includes `GEMINI_API_KEY` (not in `.env.example`). Notes that social platform credentials are configured per-brand in the UI.

---

## 4. Infrastructure Configuration Files

| File | Purpose |
|------|---------|
| `traefik/traefik.yml` | Traefik reverse proxy main config |
| `traefik/dynamic/security-headers.yml` | Traefik security headers middleware |
| `litellm/config.yaml` | LiteLLM model routing config |
| `observability/prometheus/prometheus.yml` | Prometheus scrape targets |
| `observability/grafana/grafana.ini` | Grafana server config |
| `observability/grafana/provisioning/datasources/datasources.yaml` | Grafana data source definitions |
| `observability/grafana/provisioning/dashboards/dashboards.yaml` | Grafana dashboard provisioning |
| `observability/loki/loki-config.yaml` | Loki log aggregation config |
| `observability/otel-collector/otel-collector-config.yaml` | OpenTelemetry Collector pipeline config |

---

## 5. Named Docker Volumes

| Volume | Used By |
|--------|---------|
| `traefik_certs` | Traefik (Let's Encrypt certs) |
| `pgdata` | PostgreSQL |
| `qdrant_data` | Qdrant |
| `minio_data` | MinIO |
| `valkey_data` | Valkey |
| `nats_data` | NATS |
| `n8n_data` | n8n |
| `grafana_data` | Grafana |
| `prometheus_data` | Prometheus |
| `loki_data` | Loki |

---

## 6. Security Observations

- **CRITICAL:** `.env` contains real production secrets and is tracked in git (not in `.gitignore`). These should be rotated immediately.
- All custom services run as non-root users (UID 1001).
- PostgreSQL port bound to `127.0.0.1` in dev (not exposed externally).
- VPS overlay uses external Traefik with TLS via Let's Encrypt.
