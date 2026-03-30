# Phase 9 -- Infrastructure, DevOps & Configuration Audit

**Date:** 2026-03-30
**Scope:** Dockerfiles, docker-compose files, CI/CD, configuration management, monitoring & observability

---

## 9.1 Docker Audit

### 9.1.1 Dockerfiles Summary

| Service | Base Image | Multi-stage | Non-root User | Health Check (Dockerfile) | Pinned Version |
|---|---|---|---|---|---|
| backend | python:3.13-slim | YES (builder + runtime) | YES (appuser:1001) | No (compose-level only) | YES (3.13) |
| agents | python:3.13-slim | YES (builder + runtime) | YES (appuser:1001) | No (compose-level only) | YES (3.13) |
| frontend | node:22-alpine | YES (deps + builder + runner) | YES (nextjs:1001) | No (compose-level only) | YES (22) |
| browser-worker | python:3.13-slim | YES (builder + runtime) | YES (appuser:1001) | No (compose-level only) | YES (3.13) |
| notifications | python:3.13-slim | YES (builder + runtime) | YES (appuser:1001) | No (compose-level only) | YES (3.13) |

### 9.1.2 Dockerfile Findings

#### PASS -- Multi-stage Builds
All five Dockerfiles use multi-stage builds: a `builder` stage for dependency installation and a slim runtime stage. The frontend uses a three-stage pattern (deps -> builder -> runner) which is the Next.js best practice.

#### PASS -- Non-root Users
Every Dockerfile creates a system user and switches to it with `USER`. All use UID 1001 consistently.

#### PASS -- Minimal Base Images
All Python services use `python:3.13-slim`. Frontend uses `node:22-alpine`. These are appropriate minimal images.

#### PASS -- Layer Caching
Dependencies are copied and installed before application code in all Dockerfiles, enabling effective Docker layer caching. The frontend correctly copies `package.json`/`package-lock.json` first and runs `npm ci`.

#### PASS -- No Secrets in Layers
No `.env` files, API keys, or secrets are copied into any image. All secrets are injected at runtime via `env_file` in compose.

#### PASS -- .dockerignore Files Present
All five services have `.dockerignore` files that exclude `.env`, `.env.*`, `.git/`, `__pycache__/`, `tests/`, logs, and build artifacts.

#### ISSUE-I9-01 [LOW] -- No HEALTHCHECK Directives in Dockerfiles
**Files:** All 5 Dockerfiles
None of the Dockerfiles contain a `HEALTHCHECK` instruction. Health checks are defined only in `docker-compose.yml`. This means images run outside compose (e.g., via `docker run`) lack health checks.
**Recommendation:** Add `HEALTHCHECK` to each Dockerfile as a fallback. Compose definitions will override them.

#### ISSUE-I9-02 [LOW] -- Base Image Tags Not Fully Pinned
**Files:** All Dockerfiles
Tags like `python:3.13-slim` and `node:22-alpine` are minor-version pinned but not digest-pinned. A rebuild could pull a different patch that changes behavior.
**Recommendation:** For reproducible production builds, pin to a digest: `python:3.13-slim@sha256:...`. Alternatively, accept the current approach as reasonable for a single-deployment project.

#### ISSUE-I9-03 [INFO] -- Duplicate MSSQL Driver Installation in backend + agents
**Files:** `backend/Dockerfile`, `agents/Dockerfile`
Both backend and agents Dockerfiles contain identical 8-line blocks to install the Microsoft ODBC driver (msodbcsql17) in both the builder AND runtime stages. This adds ~200MB and install complexity.
**Recommendation:** If MSSQL/Fabric connectivity is not needed by agents, remove the ODBC installation from the agents Dockerfile. If it is needed, consider a shared base image to avoid duplication.

#### ISSUE-I9-04 [LOW] -- agents Dockerfile Copies Source Twice
**File:** `agents/Dockerfile`
Application source (`shared/`, `workflows/`, `worker.py`) is copied in both the builder stage (lines 19-21) and the runtime stage (lines 52-54). The builder copy is needed for `pip install .` but the runtime copy overwrites what was already available.
**Impact:** Benign -- ensures latest source is in the final image -- but is slightly inefficient.

### 9.1.3 docker-compose.yml Findings

#### PASS -- Dependency Ordering
All services declare `depends_on` with `condition: service_healthy` for critical dependencies (e.g., backend depends on postgres being healthy). This ensures proper startup sequencing.

#### PASS -- Volume Security
Config volumes are mounted `:ro` (read-only) where appropriate (traefik config, litellm config, prometheus config, loki config, otel config, init.sql). Data volumes use named volumes, not bind mounts to host paths.

#### PASS -- Network Configuration
All services share a single `markai-net` bridge network. No service is on the default network. The VPS overlay adds an external `n8n_default` network only for services that need Traefik exposure.

#### PASS -- Restart Policies
Every service has `restart: unless-stopped`, which is appropriate for production.

#### PASS -- Health Checks on All Services
Every service in docker-compose.yml has a healthcheck defined with appropriate `interval`, `timeout`, `retries`, and `start_period` values.

#### PASS -- Environment Variable Handling
Secrets are loaded via `env_file: .env` rather than hardcoded in compose. Default values in compose use safe placeholders (e.g., `change-me`). The `.env.example` documents all required variables.

#### PASS -- Environment Separation (3-file Strategy)
- `docker-compose.yml` -- base, no host port bindings on internal services
- `docker-compose.override.yml` -- local dev, adds ports + hot-reload volumes + `MARKAI_ENV=development`
- `docker-compose.vps.yml` -- production VPS, adds Traefik labels, disables bundled Traefik/n8n, profiles out observability stack

This is a clean, well-documented separation.

#### ISSUE-I9-05 [MEDIUM] -- Resource Limits Missing on Several Services
**File:** `docker-compose.yml`
Memory limits are set for: postgres (1G), litellm (1G), backend (1G), frontend (512M), agents (2G).
Memory limits are **missing** for: traefik, qdrant, minio, valkey, nats, n8n, browser-worker, notifications, grafana, prometheus, loki, otel-collector.
**Impact:** A memory leak in any of these services could starve the entire host.
**Recommendation:** Add `deploy.resources.limits.memory` to all services. Suggested values:
- traefik: 256M
- qdrant: 1G
- minio: 512M
- valkey: 256M
- nats: 256M
- n8n: 1G
- browser-worker: 1G (runs Playwright/Chromium)
- notifications: 256M
- grafana: 512M
- prometheus: 512M
- loki: 512M
- otel-collector: 512M

#### ISSUE-I9-06 [MEDIUM] -- Docker Socket Mounted Read-Only but Still Risky
**File:** `docker-compose.yml`, line 22
Traefik has `/var/run/docker.sock:/var/run/docker.sock:ro`. While `:ro` prevents writes, any container with socket access can still query the Docker API and inspect all containers/env vars.
**Recommendation:** In production (VPS overlay), the bundled Traefik is disabled via `profiles: ["disabled"]`, so this is mitigated. For local dev, this is acceptable. Document the risk.

#### ISSUE-I9-07 [LOW] -- Hardcoded Traefik Dashboard Credentials
**File:** `docker-compose.yml`, line 31
The Traefik dashboard basic-auth password hash is hardcoded in compose labels. If the bcrypt source password is weak or shared, this is a risk.
**Recommendation:** Move to an environment variable or a file-based auth middleware.

#### ISSUE-I9-08 [LOW] -- LiteLLM Uses `main-latest` Tag
**File:** `docker-compose.yml`, line 131
`image: ghcr.io/berriai/litellm:main-latest` is a floating tag that can change on every pull.
**Recommendation:** Pin to a specific release tag (e.g., `v1.x.y`).

#### ISSUE-I9-09 [INFO] -- n8n Port 5678 Exposed on All Interfaces in Dev
**File:** `docker-compose.override.yml`, line 40
n8n binds to `5678:5678` (all interfaces) in dev, while most other internal services bind to `127.0.0.1:*`. This could expose n8n to the local network.
**Recommendation:** Change to `127.0.0.1:5678:5678` for consistency.

#### ISSUE-I9-10 [INFO] -- Grafana Port 3001 Exposed on All Interfaces in Dev
**File:** `docker-compose.override.yml`, line 77
Same as n8n -- `3001:3000` binds on all interfaces.
**Recommendation:** Change to `127.0.0.1:3001:3000`.

---

## 9.2 CI/CD Pipeline Audit

### Finding: NO CI/CD PIPELINE EXISTS

**Severity:** HIGH

There are no CI/CD configuration files in the repository:
- No `.github/workflows/` directory (only FUNDING.yml files inside node_modules, which are from npm packages)
- No `.gitlab-ci.yml`
- No `Jenkinsfile`
- No `bitbucket-pipelines.yml`
- No `Makefile` for build automation

**Impact:** Deployments are entirely manual. There is no automated:
- Linting or type checking on push/PR
- Test execution on push/PR
- Docker image building and pushing
- Deployment to staging/production
- Security scanning (SAST, dependency audit)
- Image vulnerability scanning

**Recommendation (ISSUE-I9-11 [HIGH]):** Create a minimal GitHub Actions workflow with at minimum:
1. **On PR:** lint + type-check + unit tests for backend, agents, frontend
2. **On merge to main:** build Docker images, push to registry
3. **On tag/release:** deploy to VPS (via SSH or similar)
4. **Weekly:** dependency vulnerability scan (`pip-audit`, `npm audit`)

---

## 9.3 Configuration Management Audit

### 9.3.1 Environment Separation

#### PASS -- Config Separated by Environment
The `MARKAI_ENV` variable (`development` / `production`) controls behavior. The three-file compose strategy cleanly separates dev from production. The VPS overlay sets `MARKAI_ENV: production` explicitly.

### 9.3.2 Configuration Validation

#### PASS -- Backend Uses Pydantic BaseSettings
**File:** `backend/app/config.py`
The backend uses `pydantic_settings.BaseSettings` for type-safe configuration with proper defaults and `.env` file loading.

#### PASS -- Production Startup Validation
**File:** `backend/app/config.py`, lines 128-159
In production (`MARKAI_ENV == "production"`), the backend:
1. Checks that `SECRET_KEY`, `POSTGRES_PASSWORD`, and `MINIO_SECRET_KEY` are not at default values
2. Checks that Azure AD credentials are configured
3. **Raises RuntimeError** if validation fails, preventing an insecure production deployment

This is excellent security practice.

#### PASS -- Agents Use Pydantic BaseSettings
**File:** `agents/shared/config.py`
The agents service also uses `pydantic_settings.BaseSettings` with type annotations and sensible defaults.

#### ISSUE-I9-12 [MEDIUM] -- Agents Config Lacks Production Validation
**File:** `agents/shared/config.py`
Unlike the backend, the agents service does not validate that critical secrets (POSTGRES_PASSWORD, MINIO_SECRET_KEY, LITELLM_MASTER_KEY) are set to non-default values in production. It would silently start with empty credentials.
**Recommendation:** Add startup validation similar to `backend/app/config.py` lines 128-159.

#### ISSUE-I9-13 [LOW] -- Notifications and Browser-Worker Have No Config Validation
**Files:** `notifications/app/main.py`, `browser-worker/app/main.py`
These services use plain `logging` and `os.environ` or receive config via env_file, but there is no Pydantic Settings class or startup validation.
**Recommendation:** Add Pydantic BaseSettings with required field validation for each.

### 9.3.3 Defaults Safety

#### PASS -- Dangerous Defaults Blocked in Production
Default values like `change-me` for passwords cause a hard crash when `MARKAI_ENV=production`.

#### ISSUE-I9-14 [LOW] -- Some Defaults Are Overly Permissive for Dev
**File:** `backend/app/config.py`
`SECRET_KEY` defaults to `"change-me-to-a-random-string"` and `POSTGRES_PASSWORD` to `"change-me"`. While these are blocked in production, they allow the dev environment to run with weak secrets. If a dev instance is accidentally exposed, this could be exploited.
**Recommendation:** Consider generating random defaults for dev, or requiring an explicit `.env` file even in development.

### 9.3.4 Configurable Values

#### PASS -- Comprehensive .env.example
**File:** `.env.example` (107 lines)
All configurable values are documented with placeholder values. Categories include: general, SSO, Fabric, Business Central, OpenAI, LiteLLM, PostgreSQL, Qdrant, MinIO, Valkey, NATS, n8n, social platforms, scheduler, and OTel.

#### PASS -- Scheduler Timings Are Configurable
**File:** `backend/app/config.py`, lines 104-110
Schedule intervals (morning hour, publish check interval, engagement pull interval, BC sync interval) are all environment-configurable rather than hardcoded.

---

## 9.4 Monitoring & Observability Audit

### 9.4.1 Prometheus

**File:** `observability/prometheus/prometheus.yml`

#### PASS -- Comprehensive Scrape Targets
Prometheus scrapes 8 targets:
1. `prometheus` (self)
2. `backend:8000/metrics`
3. `litellm:4000/metrics`
4. `traefik:8080` (metrics via Traefik's Prometheus entrypoint)
5. `nats:8222/varz`
6. `otel-collector:8889`
7. `minio:9000/minio/v2/metrics/cluster`
8. `qdrant:6333/metrics`

#### ISSUE-I9-15 [MEDIUM] -- Backend Has No /metrics Endpoint
**File:** `backend/app/main.py`
Prometheus is configured to scrape `backend:8000/metrics`, but the backend does not expose a `/metrics` endpoint. There is no `prometheus_client` or `prometheus-fastapi-instrumentator` dependency. The OTel instrumentor provides traces but does not automatically expose a Prometheus scrape endpoint.
**Impact:** Prometheus scrapes will 404. Backend request metrics (latency, error rates, throughput) are not being collected.
**Recommendation:** Install `prometheus-fastapi-instrumentator` and mount it on the app, or configure the OTel SDK to export metrics to the OTel collector which already exports to Prometheus.

#### ISSUE-I9-16 [MEDIUM] -- No Alerting Rules
**File:** `observability/prometheus/prometheus.yml`
There are no `rule_files` defined, no `alertmanager_config` section, and no alerting rules files exist in the `observability/` directory. Grafana has `unified_alerting: enabled = true` in its config but no alert rules are provisioned.
**Impact:** The system can be monitored visually via dashboards but there are no automated alerts for critical conditions (service down, high error rate, disk full, etc.).
**Recommendation:** Create `observability/prometheus/rules/alerts.yml` with rules for:
- Service health (target down for > 5 min)
- High error rate (> 5% 5xx responses)
- High latency (p95 > 2s)
- Disk/memory utilization
- NATS consumer lag

#### ISSUE-I9-17 [LOW] -- Prometheus Data Retention Set to 30 Days
**File:** `docker-compose.yml`, line 340
30-day retention is reasonable for a single-node deployment. No issue, just documenting.

### 9.4.2 Grafana

**File:** `observability/grafana/grafana.ini`

#### PASS -- Security Hardened
- Anonymous auth disabled
- Sign-up disabled
- Gravatar disabled
- Analytics/update checks disabled
- Default role is Viewer
- Admin password uses env var with fallback

#### PASS -- Datasources Auto-Provisioned
**File:** `observability/grafana/provisioning/datasources/datasources.yaml`
Prometheus and Loki are auto-provisioned as datasources. Loki has a derived field for `trace_id` correlation.

#### ISSUE-I9-18 [LOW] -- No Dashboard JSON Files Provisioned
**File:** `observability/grafana/provisioning/dashboards/dashboards.yaml`
The dashboards provisioner points to `/etc/grafana/provisioning/dashboards` and references a home dashboard at `markai-overview.json`, but no `.json` dashboard files exist in the repository.
**Impact:** Grafana starts with no dashboards. Operators must manually create them.
**Recommendation:** Create and commit at minimum a `markai-overview.json` dashboard with panels for service health, request rates, error rates, and latency.

#### ISSUE-I9-19 [LOW] -- Grafana Admin Password Has Weak Default
**File:** `observability/grafana/grafana.ini`, line 9
Default password is `change-me-grafana`. While Grafana is only accessible on `127.0.0.1:3001` in dev and behind `profiles: ["observability"]` in production, it should use a stronger default or require explicit configuration.

### 9.4.3 Loki (Log Aggregation)

**File:** `observability/loki/loki-config.yaml`

#### PASS -- Well-Configured
- TSDB schema v13 (current)
- Filesystem storage appropriate for single-node
- Query result caching enabled (100MB)
- Compaction with retention enabled
- Rate limiting configured (10MB/s ingestion, 20MB burst)
- Old sample rejection (168h max age)
- Analytics disabled

#### ISSUE-I9-20 [LOW] -- Auth Disabled
**File:** `observability/loki/loki-config.yaml`, line 6
`auth_enabled: false`. The file includes a comment explaining this is intentional for single-tenant deployment and that port binding is restricted to 127.0.0.1. This is acceptable but should be enabled if Loki is ever exposed.

#### ISSUE-I9-21 [MEDIUM] -- No Log Shipping from Application Containers
There is no Promtail, Docker log driver, or Alloy agent configured to ship container logs from the application services (backend, agents, frontend, etc.) into Loki. The OTel collector can receive logs via OTLP and forward to Loki, but the application services do not send logs to the OTel collector.
**Impact:** Loki receives no logs. The log aggregation pipeline is infrastructure-complete but not wired to application output.
**Recommendation:** Either:
1. Add a Promtail container that scrapes Docker container logs, OR
2. Configure Python logging in backend/agents/notifications to send to the OTel collector via OTLP, OR
3. Use the Docker logging driver to send to Loki directly

### 9.4.4 OpenTelemetry Collector

**File:** `observability/otel-collector/otel-collector-config.yaml`

#### PASS -- Pipeline Architecture
Three pipelines configured:
- **Traces:** OTLP -> memory_limiter + batch + resource tagging -> debug (console)
- **Metrics:** OTLP -> memory_limiter + batch + resource tagging -> Prometheus exporter (port 8889)
- **Logs:** OTLP -> memory_limiter + batch + resource tagging -> Loki (via OTLP/HTTP)

#### PASS -- Resource Enrichment
All telemetry is tagged with `service.namespace: markai`.

#### PASS -- Memory Protection
Memory limiter configured: 1024 MiB limit with 256 MiB spike buffer.

#### ISSUE-I9-22 [MEDIUM] -- No Trace Backend
**File:** `observability/otel-collector/otel-collector-config.yaml`, lines 57-61
Traces are exported only to `debug` (console). The config has a comment noting that Jaeger/Tempo should be added, but this has not been done. Backend OTel instrumentation sends traces to the collector, but they are discarded after being logged.
**Impact:** Distributed tracing is half-implemented: traces are generated by the backend but never stored or queryable.
**Recommendation:** Add a Tempo service to docker-compose.yml and configure the OTel collector to export traces to it. Add Tempo as a Grafana datasource.

### 9.4.5 Structured Logging

#### ISSUE-I9-23 [MEDIUM] -- No Structured (JSON) Logging in Application Services
**Files:** All Python services
All services use Python's standard `logging` module with default text format. No service uses `structlog`, `python-json-logger`, or any JSON logging formatter.
**Impact:** Logs are plain text, making them difficult to parse, filter, and correlate in Loki. Fields like `trace_id`, `brand_id`, `workflow_name` are not consistently attached as structured fields.
**Recommendation:** Adopt `structlog` with JSON output across all Python services. Bind contextual fields (request_id, trace_id, brand_id) to the logger context.

#### Traefik Logging -- PASS
**File:** `traefik/traefik.yml`, lines 42-50
Traefik uses JSON format for both application logs and access logs, with access logs filtered to 400-599 status codes. This is correct.

### 9.4.6 Health Check Endpoints

#### PASS -- All Services Have Health Endpoints
| Service | Endpoint | Checks Dependencies |
|---|---|---|
| backend | `GET /health` (simple) | No -- returns `{"status": "ok"}` |
| backend | `GET /api/v1/system/health` (rich) | Yes -- postgres, valkey, nats, minio |
| backend | `GET /api/v1/system/services` | Yes -- all 6 infra services with latency |
| frontend | `GET /` (HTTP 2xx/3xx check) | No |
| browser-worker | `GET /health` | No |
| notifications | `GET /health` | No |
| agents | Process check (`pgrep -f worker`) | No |

The Docker healthcheck for each service uses the simple endpoint (which is correct -- dependency failures should not cause the container to be killed). The rich health endpoint is available for operational dashboards.

### 9.4.7 Request Tracing

#### PARTIAL -- OpenTelemetry Instrumentation (Backend Only)
**File:** `backend/app/main.py`, lines 15-29, 113-117
The backend has OTel trace instrumentation via `FastAPIInstrumentor`, but it is only activated when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (which defaults to empty string).
**Impact:** Tracing is opt-in and disabled by default. When enabled, only the backend is instrumented -- agents, browser-worker, and notifications have no OTel instrumentation. There is no trace context propagation between services.
**Recommendation:** Add OTel instrumentation to agents and browser-worker. Ensure the `traceparent` header is propagated on inter-service HTTP calls.

### 9.4.8 Traefik (Reverse Proxy)

**File:** `traefik/traefik.yml`

#### PASS -- Security Headers
**File:** `traefik/dynamic/security-headers.yml`
Comprehensive security headers: HSTS (1 year, preload), X-Frame-Options deny, content-type nosniff, XSS filter, strict referrer policy, CSP, and stripped Server/X-Powered-By headers.

#### PASS -- HTTPS Redirect
HTTP (port 80) redirects to HTTPS (port 443) via entrypoint redirection.

#### PASS -- Let's Encrypt
ACME certificate resolver configured with HTTP challenge on the `web` entrypoint.

#### PASS -- Prometheus Metrics
Traefik exposes Prometheus metrics with entrypoint, service, and router labels.

---

## Summary of Issues

| ID | Severity | Category | Title |
|---|---|---|---|
| I9-01 | LOW | Docker | No HEALTHCHECK directives in Dockerfiles |
| I9-02 | LOW | Docker | Base image tags not fully pinned (no digest) |
| I9-03 | INFO | Docker | Duplicate MSSQL driver install in backend + agents |
| I9-04 | LOW | Docker | agents Dockerfile copies source twice |
| I9-05 | **MEDIUM** | Docker Compose | Resource limits missing on 12 of 17 services |
| I9-06 | **MEDIUM** | Docker Compose | Docker socket mounted (dev only, prod mitigated) |
| I9-07 | LOW | Docker Compose | Hardcoded Traefik dashboard credentials |
| I9-08 | LOW | Docker Compose | LiteLLM uses floating `main-latest` tag |
| I9-09 | INFO | Docker Compose | n8n port exposed on all interfaces in dev |
| I9-10 | INFO | Docker Compose | Grafana port exposed on all interfaces in dev |
| I9-11 | **HIGH** | CI/CD | No CI/CD pipeline exists at all |
| I9-12 | **MEDIUM** | Config | Agents config lacks production secret validation |
| I9-13 | LOW | Config | Notifications + browser-worker have no config validation |
| I9-14 | LOW | Config | Dev environment runs with weak default secrets |
| I9-15 | **MEDIUM** | Monitoring | Backend has no /metrics endpoint (Prometheus 404s) |
| I9-16 | **MEDIUM** | Monitoring | No alerting rules defined |
| I9-17 | LOW | Monitoring | Prometheus 30d retention (informational) |
| I9-18 | LOW | Monitoring | No Grafana dashboard JSON files provisioned |
| I9-19 | LOW | Monitoring | Grafana admin password has weak default |
| I9-20 | LOW | Monitoring | Loki auth disabled (mitigated by network binding) |
| I9-21 | **MEDIUM** | Monitoring | No log shipping from app containers to Loki |
| I9-22 | **MEDIUM** | Monitoring | No trace backend (Tempo/Jaeger) -- traces discarded |
| I9-23 | **MEDIUM** | Monitoring | No structured (JSON) logging in app services |

**Totals:** 1 HIGH, 8 MEDIUM, 9 LOW, 3 INFO

---

## What's Working Well

1. **Docker best practices:** Multi-stage builds, non-root users, minimal base images, proper .dockerignore files, and no secrets in layers across all services.
2. **Compose architecture:** Clean three-file strategy with base/dev/prod separation, no host port bindings in base, proper dependency ordering with health conditions.
3. **Configuration management:** Pydantic BaseSettings with type safety, comprehensive .env.example, and hard-fail validation that blocks production startup with insecure defaults.
4. **Observability infrastructure:** Prometheus, Grafana, Loki, and OTel Collector are all deployed with sensible configurations and auto-provisioned datasources.
5. **Security headers:** Traefik applies HSTS, CSP, frame denial, and strips identifying headers.
6. **Health checks:** Every service has a compose-level healthcheck with appropriate intervals and start periods.

## Priority Fixes

1. **(HIGH) Create CI/CD pipeline** -- Even a minimal lint+test+build workflow on GitHub Actions would dramatically improve code quality and deployment reliability.
2. **(MEDIUM) Wire up the observability pipeline** -- The infrastructure (Prometheus, Loki, OTel) is deployed but the applications are not connected to it. Add `/metrics` to backend, structured logging, log shipping, and a trace backend.
3. **(MEDIUM) Add resource limits** to all compose services to prevent runaway memory consumption on the VPS.
4. **(MEDIUM) Add production secret validation** to the agents service config, mirroring what the backend already does.
