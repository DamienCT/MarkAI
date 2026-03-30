# MARKAI Entry Points

*Generated: 2026-03-30*

---

## 1. Service Entry Points (Dockerfile CMD/ENTRYPOINT)

### 1.1 Backend (FastAPI)
- **CMD:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips *`
- **Dev override:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers --forwarded-allow-ips '*'`
- **Entry module:** `backend/app/main.py` -- creates `FastAPI` app with lifespan that starts scheduler, connects NATS, ensures MinIO bucket
- **Port:** 8000

### 1.2 Frontend (Next.js)
- **CMD:** `node server.js`
- **Build step:** `npm run build` (Next.js standalone output)
- **Entry module:** Next.js standalone `server.js` (auto-generated)
- **Port:** 3000

### 1.3 Agents (LangGraph NATS Worker)
- **CMD:** `python -m worker`
- **Entry module:** `agents/worker.py` -- connects to NATS JetStream, subscribes to 7 workflow subjects, dispatches to LangGraph graphs
- **No HTTP port** (message-driven only)

### 1.4 Browser Worker (Playwright)
- **CMD:** `uvicorn app.main:app --host 0.0.0.0 --port 8001`
- **Entry module:** `browser-worker/app/main.py` -- FastAPI app with Playwright Chromium browser lifecycle
- **Port:** 8001

### 1.5 Notifications
- **CMD:** `uvicorn app.main:app --host 0.0.0.0 --port 8002`
- **Entry module:** `notifications/app/main.py` -- FastAPI app for SSE streams and Teams webhook notifications
- **Port:** 8002

### 1.6 Third-Party Services (from docker-compose)
| Service | Command/Entry | Port |
|---------|--------------|------|
| **traefik** | Default entrypoint (config via `traefik/traefik.yml`) | 80, 443, 8080 |
| **postgres** | Default entrypoint, init script: `db/init.sql` | 5432 |
| **qdrant** | Default entrypoint | 6333 |
| **minio** | `server /data --console-address ":9001"` | 9000, 9001 |
| **valkey** | Default entrypoint | 6379 |
| **nats** | `-js -m 8222` (JetStream enabled, monitoring on 8222) | 4222, 8222 |
| **litellm** | `--config /app/config.yaml --port 4000` | 4000 |
| **n8n** | Default entrypoint | 5678 |
| **prometheus** | `--config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=30d` | 9090 |
| **loki** | `-config.file=/etc/loki/local-config.yaml` | 3100 |
| **otel-collector** | Default entrypoint (config via mounted YAML) | 4317, 4318 |
| **grafana** | Default entrypoint (config via `grafana.ini`) | 3000 (mapped to host 3001) |

---

## 2. Package.json Scripts (Frontend)

| Script | Command | Purpose |
|--------|---------|---------|
| `dev` | `next dev` | Local development server with HMR |
| `build` | `next build` | Production build (standalone output) |
| `start` | `next start` | Production server |
| `lint` | `eslint .` | Linting |

---

## 3. Scheduled Jobs (APScheduler in Backend)

All scheduled jobs are registered in `backend/app/scheduler/__init__.py` via `setup_scheduler()`, called during FastAPI lifespan startup.

| Job ID | Schedule | Module | Function | Description |
|--------|----------|--------|----------|-------------|
| `morning_jobs` | Cron: daily at `MORNING_SCHEDULE_HOUR`:`MORNING_SCHEDULE_MINUTE` (default 06:00) | `backend/app/scheduler/morning_jobs.py` | `run_morning_jobs()` | Orchestrator: BC sync + engagement pull + evaluation NATS trigger + content top-up |
| `publish_checker` | Interval: every `PUBLISH_CHECK_INTERVAL_MINUTES` min (default 15) | `backend/app/scheduler/publish_checker.py` | `check_due_content()` | Check for content due to be published |
| `engagement_puller` | Interval: every `ENGAGEMENT_PULL_INTERVAL_HOURS` hrs (default 6) | `backend/app/scheduler/engagement_puller.py` | `pull_all_engagement()` | Pull engagement metrics from social platforms |
| `bc_sync` | Interval: every `BC_SYNC_INTERVAL_HOURS` hrs (default 6) | `backend/app/scheduler/bc_sync.py` | `sync_bc_products()` | Sync products from Business Central via Fabric |
| `ai_model_discovery` | Cron: daily at 03:00 | `backend/app/scheduler/model_discovery.py` | `discover_ai_models()` | Discover available AI models from LLM providers |

**Timezone:** Configurable via `SCHEDULER_TIMEZONE` (default `Indian/Mauritius`).

### Morning Jobs Detail (`run_morning_jobs`)
Executes sequentially:
1. BC product sync (`sync_bc_products`)
2. Engagement pull (`pull_all_engagement`)
3. Emit `evaluation.trigger` message to NATS
4. Content top-up -- finds nearest queued calendar item within `content_generation_days_ahead` window and publishes `content.generate` to NATS

---

## 4. Background Workers / Message-Driven Processes

### 4.1 Agents Worker (`agents/worker.py`)

Long-running NATS JetStream consumer. Subscribes to 7 durable consumers on the `WORKFLOWS` stream:

| Subject Pattern | Durable Name | Graph |
|----------------|--------------|-------|
| `research.>` | `research-worker` | `research_graph` |
| `strategy.>` | `strategy-worker` | `strategy_graph` |
| `planning.>` | `planning-worker` | `planning_graph` |
| `content.>` | `content-worker` | `content_graph` |
| `evaluation.>` | `evaluation-worker` | `evaluation_graph` |
| `product.>` | `product-worker` | `product_intel_graph` |
| `adaptation.>` | `adaptation-worker` | `adaptation_graph` |

**Workflow chaining logic** (activation trigger):
- `research` -> `strategy.trigger`
- `strategy` -> `planning.trigger`
- `planning` -> `content.generate` (sequential: one item at a time via `remaining_queue`)
- `evaluation` -> `adaptation.trigger` (always, regardless of trigger type)
- `adaptation` -> `planning.trigger` (only if tier2/3 changes and depth < 2)
- `product` -> `strategy.trigger` (only if brand has existing research)

**Idempotency guard:** Skips duplicate workflows of same type for same brand if one is already running (within 30 min window).

**Timeout:** Configurable via `WORKFLOW_TIMEOUT_SECONDS` env var (default 1800s / 30 min).

### 4.2 NATS JetStream
- Stream: `WORKFLOWS`
- Subjects: `research.>`, `strategy.>`, `content.>`, `evaluation.>`, `product.>`, `planning.>`, `adaptation.>`
- Retention: workqueue
- Max age: 7 days

---

## 5. Database Initialization / Migration Scripts

### 5.1 Init Script
- **File:** `db/init.sql`
- **Loaded by:** PostgreSQL container via `docker-entrypoint-initdb.d/01-init.sql` (runs only on first container creation when pgdata volume is empty)
- **Contents:** Full schema creation (16 tables), indexes, seed data for `ai_model_categories` and `app_settings`, `update_updated_at_column()` trigger function applied to all tables with `updated_at`

### 5.2 Alembic Migrations
- **Config:** `backend/alembic.ini`
- **Env:** `backend/alembic/env.py`
- **Versions dir:** `backend/alembic/versions/` (currently empty -- `.gitkeep` only)
- **Engine:** async via `asyncpg`
- **Models imported:** User, Notification, AuditLog, ScheduledJobLog, Brand, Content, Campaign, CalendarItem, Approval, PromptVersion, AgentRun, EngagementMetric, Adaptation, Competitor, Product, AIModelCategory, AIModel, AIModelSelection
- **Usage:** `alembic upgrade head` (must be run manually or added to deploy scripts; not automated in any CI/CD)

**Note:** Alembic is set up but has no migration versions yet. Schema is currently managed entirely by `db/init.sql`.

---

## 6. Executable Scripts Summary

No standalone shell scripts found in the project (only `db/init.sql` for database init). All operations are driven by:
- Docker Compose commands (`docker compose up -d`)
- Python module execution (`python -m worker`)
- Uvicorn server commands
- Node.js server execution (`node server.js`)

---

## 7. Service Dependency Graph

```
frontend -> backend -> postgres, qdrant, minio, valkey, nats, litellm
agents -> nats, litellm, postgres, qdrant, minio
browser-worker -> (standalone, called by agents/backend via HTTP)
notifications -> postgres, valkey
litellm -> valkey
n8n -> (standalone, receives webhooks from backend)
grafana -> prometheus, loki
otel-collector -> (receives telemetry, forwards to Loki/etc.)
```
