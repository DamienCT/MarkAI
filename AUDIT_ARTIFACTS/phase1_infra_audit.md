# Phase 1: Infrastructure Audit Report

**Date:** 2026-03-30
**Scope:** All non-Python, non-TypeScript infrastructure files
**Auditor:** Claude Opus 4.6 (automated)

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 12    |
| MEDIUM   | 18    |
| LOW      | 11    |
| **Total**| **44**|

---

## CRITICAL Findings

### C-1. Hardcoded Traefik Dashboard Credentials in docker-compose.yml

- **File:** `docker-compose.yml`, line 30
- **Category:** SECURITY
- **Description:** The Traefik dashboard basic-auth password is hardcoded as a bcrypt hash directly in the compose file. This hash is committed to version control and anyone with repo access can attempt to brute-force it offline. The actual cleartext password used to generate this hash is unknown but fixed.
- **Proposed fix:** Move the basicauth users string to an environment variable in `.env` (e.g., `TRAEFIK_DASHBOARD_AUTH`) and reference it via `${TRAEFIK_DASHBOARD_AUTH}`. Add placeholder to `.env.example` and `.env.vps.example`.

### C-2. Grafana Admin Password Uses Insecure Default

- **File:** `observability/grafana/grafana.ini`, line 9
- **Category:** SECURITY
- **Description:** `admin_password = ${GF_SECURITY_ADMIN_PASSWORD:change-me-grafana}` uses `change-me-grafana` as the default. If `GF_SECURITY_ADMIN_PASSWORD` is not set in the environment (it is NOT in `.env.example` or `.env.vps.example`), Grafana runs with this trivially guessable password. Since `.env.example` and `.env.vps.example` contain no `GF_SECURITY_ADMIN_PASSWORD`, this default will always be used.
- **Proposed fix:** Add `GF_SECURITY_ADMIN_PASSWORD=CHANGE_ME_GENERATE_STRONG_PASSWORD` to `.env.example` and `.env.vps.example`. Pass it as an environment variable to the Grafana service in `docker-compose.yml`.

### C-3. GEMINI_API_KEY Missing from .env.example and LiteLLM Config

- **File:** `.env.example` (missing), `litellm/config.yaml` (missing), `docker-compose.yml` line 141 (missing)
- **Category:** BUG
- **Description:** The `.env.vps.example` includes `GEMINI_API_KEY` and the backend/agents code references it, but:
  1. `.env.example` does not include `GEMINI_API_KEY` at all
  2. `litellm/config.yaml` has no Gemini model entries
  3. `docker-compose.yml` does not pass `GEMINI_API_KEY` to the LiteLLM service environment
  This means Gemini models are only accessible via direct API calls in backend/agents code, bypassing the LiteLLM proxy gateway -- defeating the purpose of having a unified LLM gateway.
- **Proposed fix:** Add `GEMINI_API_KEY` to `.env.example`. Add Gemini model entries to `litellm/config.yaml`. Pass `GEMINI_API_KEY` to the LiteLLM service in `docker-compose.yml`.

---

## HIGH Findings

### H-1. Docker Socket Mounted Read-Only but Still High Risk

- **File:** `docker-compose.yml`, line 22
- **Category:** SECURITY
- **Description:** `/var/run/docker.sock:/var/run/docker.sock:ro` gives Traefik (and any attacker who compromises it) full read access to the Docker API, which can enumerate all containers, environment variables, and potentially escalate privileges. The `:ro` flag only prevents writes at the filesystem level -- the Docker API socket still allows read operations that expose secrets.
- **Proposed fix:** In production (VPS), the bundled Traefik is disabled (good). For local dev, this is acceptable. Document the risk. Consider using Traefik's Docker API read-only mode or a socket proxy like `tecnativa/docker-socket-proxy`.

### H-2. No Resource Limits on 9 Services

- **File:** `docker-compose.yml`
- **Category:** PERFORMANCE / RELIABILITY
- **Description:** The following services have NO `deploy.resources.limits.memory` set: traefik, qdrant, minio, valkey, nats, n8n, browser-worker, notifications, grafana, prometheus, loki, otel-collector. A single runaway service can consume all host memory and OOM-kill others.
- **Proposed fix:** Add memory limits to all services. Suggested values:
  - traefik: 256M
  - qdrant: 1G
  - minio: 512M
  - valkey: 256M
  - nats: 256M
  - n8n: 1G
  - browser-worker: 2G (Playwright/Chromium is memory-hungry)
  - notifications: 256M
  - grafana: 512M
  - prometheus: 512M
  - loki: 512M
  - otel-collector: 256M

### H-3. Qdrant Has No Authentication

- **File:** `docker-compose.yml`, lines 61-74
- **Category:** SECURITY
- **Description:** Qdrant is running without any API key or authentication. Any container on the `markai-net` network (or anyone with access to the exposed dev port 6333) can read/write/delete all vector data.
- **Proposed fix:** Set `QDRANT__SERVICE__API_KEY` environment variable on the Qdrant service and pass the same key to backend/agents via `.env`. Add `QDRANT_API_KEY` to `.env.example` and `.env.vps.example`.

### H-4. MinIO Credentials Use Weak Defaults

- **File:** `docker-compose.yml`, lines 82-83
- **Category:** SECURITY
- **Description:** `MINIO_ROOT_USER` defaults to `markai-minio` and `MINIO_ROOT_PASSWORD` defaults to `change-me`. If the `.env` file is missing or these vars are unset, MinIO starts with trivially guessable credentials.
- **Proposed fix:** Remove defaults from the compose file (use `${MINIO_ACCESS_KEY}` without `:-` fallback) so the service fails to start if credentials are not explicitly configured.

### H-5. PostgreSQL Password Has Weak Default

- **File:** `docker-compose.yml`, line 47
- **Category:** SECURITY
- **Description:** `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change-me}` provides a weak default password. If `.env` is missing, Postgres starts with `change-me` as the password.
- **Proposed fix:** Remove the `:-change-me` default so the service fails to start without an explicit password.

### H-6. Valkey (Redis) Has No Authentication

- **File:** `docker-compose.yml`, lines 97-110
- **Category:** SECURITY
- **Description:** Valkey runs without `--requirepass`. Any service on the Docker network can access the cache without authentication. The LiteLLM config also connects to Valkey without a password.
- **Proposed fix:** Add `command: ["valkey-server", "--requirepass", "${VALKEY_PASSWORD}"]` and update LiteLLM and all consumers to provide the password.

### H-7. NATS Has No Authentication

- **File:** `docker-compose.yml`, lines 113-127
- **Category:** SECURITY
- **Description:** NATS runs with just `-js -m 8222` (JetStream + monitoring). No authentication is configured. Any container on the network can publish/subscribe to any subject.
- **Proposed fix:** Configure NATS authentication (token or nkey) and update all NATS clients.

### H-8. CSP Contains 'unsafe-inline' and 'unsafe-eval'

- **File:** `traefik/dynamic/security-headers.yml`, line 15
- **Category:** SECURITY
- **Description:** The Content Security Policy includes `'unsafe-inline'` for both `script-src` and `style-src`, and `'unsafe-eval'` for `script-src`. This significantly weakens XSS protection.
- **Proposed fix:** Use nonces or hashes for inline scripts. For Next.js, `unsafe-inline` for styles may be necessary, but `unsafe-eval` for scripts should be removed once the app is confirmed to work without it.

### H-9. LiteLLM Uses Floating Tag `main-latest`

- **File:** `docker-compose.yml`, line 131
- **Category:** RELIABILITY
- **Description:** `ghcr.io/berriai/litellm:main-latest` is a floating tag that changes with every push to main. This can introduce breaking changes silently during rebuilds.
- **Proposed fix:** Pin to a specific version tag, e.g., `ghcr.io/berriai/litellm:v1.65.5`.

### H-10. Notifications Service Uses `valkey` Package but Backend Uses `redis`

- **File:** `notifications/pyproject.toml` (line 18: `valkey>=6.1`), `backend/pyproject.toml` (line 25: `redis>=7.1`)
- **Category:** BUG / QUALITY
- **Description:** The notifications service depends on the `valkey` Python package while the backend depends on `redis`. Both connect to the same Valkey server. While Valkey is Redis-compatible and the `redis` Python package works with it, using two different client libraries for the same server is inconsistent and could lead to subtle behavioral differences.
- **Proposed fix:** Standardize on one package across all services (either `redis` or `valkey`).

### H-11. Alembic Versions Directory Is Empty

- **File:** `backend/alembic/versions/` (empty directory)
- **Category:** BUG
- **Description:** The `alembic/versions/` directory contains no migration files. The database schema is initialized via `db/init.sql` only. This means Alembic is configured and imported into the Docker image but never actually used. Any schema changes after initial deployment have no migration path.
- **Proposed fix:** Generate an initial Alembic migration from the current schema (`alembic revision --autogenerate -m "initial"`). Future schema changes must go through Alembic, not manual SQL edits.

### H-12. n8n and Backend Port Bindings Exposed on 0.0.0.0 in Dev

- **File:** `docker-compose.override.yml`, lines 40-41 (n8n: `5678:5678`), lines 44-45 (backend: `8000:8000`)
- **Category:** SECURITY
- **Description:** n8n and backend ports are bound to `0.0.0.0` (all interfaces) in the dev override, meaning they are accessible from the network. Other services correctly use `127.0.0.1:` prefix.
- **Proposed fix:** Change to `127.0.0.1:5678:5678` and `127.0.0.1:8000:8000`.

---

## MEDIUM Findings

### M-1. Grafana Dashboard Path References Non-Existent File

- **File:** `observability/grafana/grafana.ini`, line 21
- **Category:** BUG
- **Description:** `default_home_dashboard_path = /etc/grafana/provisioning/dashboards/markai-overview.json` but no `markai-overview.json` file exists in the provisioned dashboards directory. Grafana will fail to load the default dashboard.
- **Proposed fix:** Either create the `markai-overview.json` dashboard file or remove the `default_home_dashboard_path` setting.

### M-2. Prometheus Scrapes Traefik on Port 8080 but Traefik Doesn't Expose Metrics There in Base Config

- **File:** `observability/prometheus/prometheus.yml`, line 25; `traefik/traefik.yml`, lines 53-58
- **Category:** BUG
- **Description:** Prometheus is configured to scrape `traefik:8080` but the Traefik static config exposes the Prometheus metrics on the `web` entryPoint (port 80), not on 8080. The `api.insecure: false` setting means the dashboard/API is not served on 8080 unless explicitly configured. However, the dev override exposes port 8080. The metrics endpoint configuration and the scrape target may not align.
- **Proposed fix:** Either add `metrics.prometheus.entryPoint: traefik` with a separate entryPoint on 8080, or change Prometheus to scrape the correct endpoint.

### M-3. Loki Retention Not Configured

- **File:** `observability/loki/loki-config.yaml`
- **Category:** PERFORMANCE
- **Description:** The compactor has `retention_enabled: true` but no `retention_period` is specified in `limits_config`. Without an explicit retention period, logs are never deleted and disk usage grows unbounded.
- **Proposed fix:** Add `retention_period: 720h` (30 days) to `limits_config`.

### M-4. OTel Collector Traces Go to Debug Only

- **File:** `observability/otel-collector/otel-collector-config.yaml`, line 61
- **Category:** QUALITY
- **Description:** Traces are exported only to `debug` (console stdout). No persistent trace backend (Jaeger/Tempo) is configured. Trace data is effectively discarded.
- **Proposed fix:** This is documented in the config comments (good). When traces are needed, deploy Tempo and wire it up. Low priority but tracked here for completeness.

### M-5. No CPU Limits on Any Service

- **File:** `docker-compose.yml` (all services)
- **Category:** PERFORMANCE
- **Description:** No service has CPU limits set (`deploy.resources.limits.cpus`). A single service can starve all others of CPU.
- **Proposed fix:** Add CPU limits to all services, especially compute-heavy ones (agents, browser-worker, litellm).

### M-6. Agents Dockerfile Installs Playwright Chromium Twice

- **File:** `agents/Dockerfile`, line 46
- **Category:** PERFORMANCE
- **Description:** The agents Dockerfile installs Playwright Chromium via `playwright install --with-deps chromium` in the runtime stage. This adds ~400MB+ to the image. The agents service primarily processes LLM workflows -- Playwright should only be in `browser-worker`. If agents need browser capabilities, they should call the browser-worker service via HTTP.
- **Proposed fix:** Remove the `playwright install --with-deps chromium` line from `agents/Dockerfile` unless agents genuinely need a local browser. Remove `playwright>=1.58` from `agents/pyproject.toml` if unused.

### M-7. Backend Dockerfile Copies Source Twice

- **File:** `backend/Dockerfile`, lines 22 + 50
- **Category:** PERFORMANCE
- **Description:** `COPY app/ app/` appears in both the builder stage (line 22) and the runtime stage (line 50). The runtime stage already copies the installed packages from builder. The second COPY of source code is needed for the runtime but means source code changes invalidate the Docker cache at line 50, which is correct. However, the `COPY pyproject.toml .` + `COPY app/ app/` in the builder stage could be optimized by copying `pyproject.toml` first, running `pip install` for dependencies only, then copying `app/`.
- **Proposed fix:** Split the builder into: (1) copy pyproject.toml, (2) install deps, (3) copy app source. This way dependency layer is cached independently of source changes.

### M-8. No Health Check on Grafana, Prometheus, Loki, OTel Collector

- **File:** `docker-compose.yml`, lines 316-364
- **Category:** RELIABILITY
- **Description:** Grafana, Prometheus, Loki, and OTel Collector have no healthcheck configured. Docker cannot automatically detect if these services are unhealthy.
- **Proposed fix:** Add healthchecks:
  - Grafana: `curl -f http://localhost:3000/api/health`
  - Prometheus: `curl -f http://localhost:9090/-/healthy`
  - Loki: `curl -f http://localhost:3100/ready`
  - OTel: `curl -f http://localhost:13133/` (health extension, needs to be enabled)

### M-9. Agents `depends_on` Uses `service_started` Instead of `service_healthy`

- **File:** `docker-compose.yml`, lines 260-271
- **Category:** RELIABILITY
- **Description:** Agents depends on `nats`, `litellm`, `qdrant`, and `minio` with `condition: service_started` instead of `service_healthy`. This means agents may start before these services are ready, causing connection errors on startup.
- **Proposed fix:** Change to `condition: service_healthy` for all dependencies that have healthchecks defined (nats, litellm, qdrant, minio all have healthchecks).

### M-10. Backend `depends_on` Inconsistency

- **File:** `docker-compose.yml`, lines 201-213
- **Category:** RELIABILITY
- **Description:** Backend depends on `qdrant`, `minio`, and `nats` with `service_started` but on `postgres` and `valkey` with `service_healthy`. Since qdrant, minio, and nats all have healthchecks defined, they should also use `service_healthy`.
- **Proposed fix:** Change qdrant, minio, and nats dependencies to `condition: service_healthy`.

### M-11. Notifications `depends_on` Uses `service_started` for Valkey

- **File:** `docker-compose.yml`, line 311
- **Category:** RELIABILITY
- **Description:** Notifications depends on `valkey` with `condition: service_started` instead of `service_healthy`. Valkey has a healthcheck defined.
- **Proposed fix:** Change to `condition: service_healthy`.

### M-12. NATS JetStream Data Directory Not Configured

- **File:** `docker-compose.yml`, lines 113-127
- **Category:** RELIABILITY
- **Description:** NATS is started with `-js` (JetStream enabled) and a volume mount for `/data`, but the NATS command does not include `--store_dir /data`. The default JetStream store directory may not be `/data`, meaning messages could be stored in a non-persistent location inside the container.
- **Proposed fix:** Change command to `"-js -m 8222 --store_dir /data"`.

### M-13. Frontend Dockerfile Default Build Arg Leaks Internal Hostname

- **File:** `frontend/Dockerfile`, line 20
- **Category:** SECURITY / QUALITY
- **Description:** `ARG NEXT_PUBLIC_API_URL=https://api.markai.srv1191974.hstgr.cloud` hardcodes the production domain as the default build arg. This means local `docker compose build` without args creates an image pointing at production.
- **Proposed fix:** Change default to `http://localhost:8000` or remove the default entirely so builds fail explicitly when the arg is not provided.

### M-14. `app_settings` Table Has No `NOT NULL` on `updated_at`

- **File:** `db/init.sql`, line 467
- **Category:** BUG
- **Description:** `updated_at TIMESTAMPTZ DEFAULT NOW()` lacks `NOT NULL`. Other tables consistently use `NOT NULL DEFAULT NOW()` for timestamps.
- **Proposed fix:** Add `NOT NULL` constraint: `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.

### M-15. `ai_model_categories` Table Has No `NOT NULL` on `created_at`

- **File:** `db/init.sql`, line 419
- **Category:** BUG
- **Description:** `created_at TIMESTAMPTZ DEFAULT NOW()` lacks `NOT NULL`, inconsistent with all other tables.
- **Proposed fix:** Add `NOT NULL` constraint.

### M-16. `ai_model_selections.set_at` and `ai_models.discovered_at` Lack `NOT NULL`

- **File:** `db/init.sql`, lines 431, 447
- **Category:** BUG
- **Description:** `discovered_at TIMESTAMPTZ DEFAULT NOW()` and `set_at TIMESTAMPTZ DEFAULT NOW()` lack `NOT NULL`, inconsistent with the rest of the schema.
- **Proposed fix:** Add `NOT NULL` constraints.

### M-17. Mixed UUID Generation Functions

- **File:** `db/init.sql`
- **Category:** QUALITY
- **Description:** Older tables use `uuid_generate_v4()` (from uuid-ossp extension) while newer tables (`ai_model_categories`, `ai_models`, `ai_model_selections`) use `gen_random_uuid()` (from pgcrypto). Both work but the inconsistency suggests different authoring sessions and could confuse maintainers.
- **Proposed fix:** Standardize on `gen_random_uuid()` (built into PG 13+, more modern) across all tables.

### M-18. Seed Script Schema Mismatch

- **File:** `scripts/seed-dev.py`, lines 27-91
- **Category:** BUG
- **Description:** The seed script sends fields like `website`, `tone_settings`, `visual_identity`, `content_pillars`, `excluded_topics`, `brand_safety_rules`, `social_links`, `social_credentials`, `posting_cadence`, `approval_chain`, `competitor_urls`, `bc_vendor_filter` -- but the `brands` table in `db/init.sql` has completely different columns (`website_url`, `tone_of_voice`, `brand_guidelines`, `color_palette`, `target_audience`). The seed script will fail with 400 errors because the API schema likely does not match these field names.
- **Proposed fix:** Update the seed script to match the actual database schema and API endpoints.

---

## LOW Findings

### L-1. `.gitignore` Lists `docker-compose.override.yml` but Not `docker-compose.dev.yml`

- **File:** `.gitignore`, line 28
- **Category:** QUALITY
- **Description:** The override file is correctly gitignored. The project docs reference `docker-compose.dev.yml` in some places but this file does not exist (the actual file is `docker-compose.override.yml`). Minor naming inconsistency.
- **Proposed fix:** Ensure docs consistently refer to `docker-compose.override.yml`.

### L-2. Promptfoo Config References Non-Existent Prompt Files

- **File:** `eval/promptfooconfig.yaml`, lines 11-12
- **Category:** BUG
- **Description:** References `file://prompts/content_generation.txt` and `file://prompts/research_summary.txt` but no `eval/prompts/` directory exists. The eval suite cannot run.
- **Proposed fix:** Create the referenced prompt template files or update the paths.

### L-3. Notifications `.dockerignore` Is Less Comprehensive

- **File:** `notifications/.dockerignore`
- **Category:** QUALITY
- **Description:** Missing entries present in other services' `.dockerignore` files: `dist/`, `build/`, `.venv/`, `venv/`, `.env.*`, `*.log`, `.pytest_cache/`, `.ruff_cache/`. Could lead to larger Docker build contexts.
- **Proposed fix:** Align with the more comprehensive `.dockerignore` from backend/agents.

### L-4. Browser-Worker `.dockerignore` Missing Test/Cache Entries

- **File:** `browser-worker/.dockerignore`
- **Category:** QUALITY
- **Description:** Missing `tests/`, `.pytest_cache/`, `.ruff_cache/` entries compared to backend/agents.
- **Proposed fix:** Add missing entries.

### L-5. `litellm_settings.request_timeout: 120` May Be Too Low for Image/Video Generation

- **File:** `litellm/config.yaml`, line 64
- **Category:** PERFORMANCE
- **Description:** 120-second timeout may not be sufficient for video generation models like `sora-2` and `sora-2-pro`, which can take several minutes to complete.
- **Proposed fix:** Increase to 300 or make it configurable per-model.

### L-6. Traefik Access Log Only Captures 400-599 Status Codes

- **File:** `traefik/traefik.yml`, lines 49-50
- **Category:** QUALITY
- **Description:** Filtering access logs to only error status codes means successful requests are not logged. This makes it harder to debug routing issues or analyze traffic patterns.
- **Proposed fix:** Consider logging all requests in dev, and keeping the filter only in production.

### L-7. Prometheus Has 30d Retention Without Disk Limit

- **File:** `docker-compose.yml`, line 340
- **Category:** PERFORMANCE
- **Description:** `--storage.tsdb.retention.time=30d` without a size-based limit (`--storage.tsdb.retention.size`) means Prometheus data can grow unbounded if scrape targets increase.
- **Proposed fix:** Add `--storage.tsdb.retention.size=5GB` (or appropriate value).

### L-8. Loki Grafana Datasource `derivedFields` Reference May Be Broken

- **File:** `observability/grafana/provisioning/datasources/datasources.yaml`, line 23
- **Category:** BUG
- **Description:** `datasourceUid: prometheus` references Prometheus for trace correlation, but traces are not stored in Prometheus. If a trace backend (Tempo) is added later, this should reference the Tempo datasource UID.
- **Proposed fix:** Update when a trace backend is deployed. Document as a known TODO.

### L-9. Agents Build System Inconsistency

- **File:** `agents/pyproject.toml` (uses setuptools), others use hatchling
- **Category:** QUALITY
- **Description:** The agents service uses `setuptools` as its build backend while all other Python services use `hatchling`. This inconsistency could confuse developers.
- **Proposed fix:** Migrate agents to hatchling for consistency.

### L-10. Duplicate Scrape Intervals in Prometheus Config

- **File:** `observability/prometheus/prometheus.yml`, lines 15, 20, 26, 37
- **Category:** QUALITY
- **Description:** `scrape_interval: 15s` is set both globally (line 2) and again on individual job configs (lines 15, 20, 26, 37). The per-job values are identical to the global default and thus redundant.
- **Proposed fix:** Remove redundant per-job `scrape_interval` settings where they match the global default.

### L-11. `engagement_metrics.channel` Has No CHECK Constraint

- **File:** `db/init.sql`, line 281
- **Category:** BUG
- **Description:** `engagement_metrics.channel VARCHAR(50) NOT NULL` lacks a CHECK constraint, unlike `calendar_items.channel` and `adaptations.target_channel` which enumerate valid channels. Inconsistent validation could allow invalid channel names in metrics.
- **Proposed fix:** Add `CHECK (channel IN ('instagram', 'facebook', 'linkedin', 'youtube', 'tiktok', 'x', 'website_blog', 'teams'))`.

---

## Files Audited

| File | Status |
|------|--------|
| `docker-compose.yml` | Audited |
| `docker-compose.vps.yml` | Audited |
| `docker-compose.override.yml` | Audited |
| `backend/Dockerfile` | Audited |
| `frontend/Dockerfile` | Audited |
| `agents/Dockerfile` | Audited |
| `browser-worker/Dockerfile` | Audited |
| `notifications/Dockerfile` | Audited |
| `db/init.sql` | Audited |
| `backend/alembic.ini` | Audited |
| `backend/alembic/env.py` | Audited |
| `backend/alembic/versions/` | Audited (empty) |
| `litellm/config.yaml` | Audited |
| `observability/prometheus/prometheus.yml` | Audited |
| `observability/grafana/grafana.ini` | Audited |
| `observability/grafana/provisioning/datasources/datasources.yaml` | Audited |
| `observability/grafana/provisioning/dashboards/dashboards.yaml` | Audited |
| `observability/otel-collector/otel-collector-config.yaml` | Audited |
| `observability/loki/loki-config.yaml` | Audited |
| `traefik/traefik.yml` | Audited |
| `traefik/dynamic/security-headers.yml` | Audited |
| `.env.example` | Audited |
| `.env.vps.example` | Audited |
| `.env` | Audited (not in git) |
| `.gitignore` | Audited |
| `backend/.dockerignore` | Audited |
| `agents/.dockerignore` | Audited |
| `frontend/.dockerignore` | Audited |
| `browser-worker/.dockerignore` | Audited |
| `notifications/.dockerignore` | Audited |
| `backend/pyproject.toml` | Audited |
| `agents/pyproject.toml` | Audited |
| `browser-worker/pyproject.toml` | Audited |
| `notifications/pyproject.toml` | Audited |
| `eval/promptfooconfig.yaml` | Audited |
| `scripts/seed-dev.py` | Audited |
| `scripts/column-discovery.py` | Audited |
| `scripts/bc-table-discovery.py` | Audited |

---

## Priority Remediation Order

1. **Immediate (CRITICAL):** C-1 (Traefik creds), C-2 (Grafana password), C-3 (Gemini config gap)
2. **This sprint (HIGH):** H-3 through H-7 (service authentication), H-8 (CSP), H-9 (LiteLLM pinning), H-11 (Alembic), H-12 (port bindings)
3. **Next sprint (MEDIUM):** M-1 through M-18 (resource limits, healthchecks, depends_on, schema consistency)
4. **Backlog (LOW):** L-1 through L-11 (quality, minor inconsistencies)
