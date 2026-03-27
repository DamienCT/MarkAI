# MARKAI Pre-Production Audit Report

**Date:** 2026-03-27
**Scope:** Full codebase — backend, agents, frontend, infrastructure, Docker, database, observability
**Files audited:** ~200+ source files across 4 parallel audit passes

---

## Executive Summary

| Severity | Backend | Agents | Frontend | Infra | **Total** |
|----------|---------|--------|----------|-------|-----------|
| CRITICAL | 5 | 6 | 3 | 5 | **19** |
| HIGH | 10 | 9 | 7 | 10 | **36** |
| MEDIUM | 14 | 11 | 10 | 12 | **47** |
| LOW | 14 | 10 | 13 | 8 | **45** |
| **Total** | **43** | **36** | **33** | **35** | **147** |

**Top blockers for production:** NATS ack/timeout mismatch causing duplicate workflow runs, field name mismatches silently breaking content generation, default secrets still in config, CORS bypass, frontend Docker build previously broken, missing ODBC driver in agents container.

---

## 1. CRITICAL Issues (19)

### Infrastructure (5)

| ID | Issue | File | Impact |
|----|-------|------|--------|
| I-C1 | Production secrets at default `change-me` values (`POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`) | `.env:42,51` | Full DB/storage compromise |
| I-C2 | `NEXT_PUBLIC_API_URL` missing from `.env` -- frontend calls `localhost:8000` in production | `.env`, `next.config.ts:6` | Frontend completely non-functional in prod |
| I-C3 | `N8N_WEBHOOK_BASE` points to `example.com` -- publishing aborts (backend checks for this) | `.env:63`, `publish_service.py:76` | All social publishing fails |
| I-C4 | `N8N_WEBHOOK_SECRET` missing from `.env` -- webhook auth disabled | `.env`, `config.py:70` | Unauthenticated webhook callbacks |
| I-C5 | Real API keys (`OPENAI_API_KEY`, `AZURE_AD_CLIENT_SECRET`, etc.) in plaintext `.env` -- may be in git history | `.env:7-35` | Key compromise if repo shared |

### Backend (5)

| ID | Issue | File | Impact |
|----|-------|------|--------|
| B-C1 | CORS allows wildcard `*` with credentials when `FRONTEND_URL` is empty | `main.py:69-76` | Browsers block all cross-origin requests or app is wide open |
| B-C2 | Global exception handler echoes any `Origin` header back, bypassing CORS for error responses | `main.py:93-96` | Malicious sites can read 500-error bodies cross-origin |
| B-C3 | `PUT /api/v1/settings/` has no role check -- any authenticated user can overwrite all app settings | `settings.py:25-41` | Privilege escalation |
| B-C4 | Default secrets in `config.py` (`SECRET_KEY="change-me-to-a-random-string"`, etc.) with no fail-fast | `config.py:14,27,44` | App runs with known passwords in prod |
| B-C5 | `app_settings` table has no SQLAlchemy model -- raw SQL only, invisible to Alembic | `settings.py:18-22` | 500 errors if init.sql not run |

### Agents (6)

| ID | Issue | File | Impact |
|----|-------|------|--------|
| A-C1 | NATS `ack_wait=300s` (5 min) but `WORKFLOW_TIMEOUT=1800s` (30 min) -- messages redeliver while workflow still running | `nats_consumer.py:55`, `worker.py:25` | **Duplicate workflow runs, double API charges, corrupted state** |
| A-C2 | `store_adaptations()` schema mismatch -- evaluation nodes pass `{tier, description, confidence}` but DB function expects `{source_content_id, target_channel, adapted_text}` | `evaluation/nodes.py:108-119`, `database.py:404-427` | Evaluation pipeline silently stores empty records |
| A-C3 | `calendar_item` uses column `channel` in DB but content nodes read `item.get('platform')` | `content/nodes.py:68,100,126,231` | All content generation receives empty platform -- prompts are platform-unaware |
| A-C4 | `calendar_item` uses column `item_type` in DB but content nodes read `item.get('content_type')` | `content/nodes.py:69` | Content type (reel/story/carousel) ignored in all prompts |
| A-C5 | Dockerfile `pip install .` runs before source dirs are COPYed -- build fails or installs zero packages | `Dockerfile:14-16` | **Docker image build failure** |
| A-C6 | Missing ODBC Driver 17 in Docker image -- `unixodbc-dev` headers installed but not `msodbcsql17` | `Dockerfile:5-12`, `fabric.py:55` | All Fabric/BC SQL queries fail at runtime |

### Frontend (3)

| ID | Issue | File | Impact |
|----|-------|------|--------|
| F-C1 | Secrets committed in `.env.local` (`AZURE_AD_CLIENT_SECRET`, `NEXTAUTH_SECRET`) | `.env.local:1-7` | Full auth compromise if repo exposed |
| F-C2 | SSE notification stream has no authentication -- `EventSource` doesn't support custom headers | `Header.tsx:67-69` | Unauthenticated access to notification stream |
| F-C3 | "Mark All Read" only clears local state, never calls backend -- notifications reappear on refresh | `Header.tsx:113-116` | Broken feature |

---

## 2. HIGH Issues (36)

### Infrastructure (10)

| ID | Issue | File |
|----|-------|------|
| I-H1 | Traefik dashboard exposed without authentication on port 8080 | `traefik.yml:6-7`, `compose:16` |
| I-H2 | Frontend, agents, browser-worker, notifications missing Docker healthchecks | `compose` (4 services) |
| I-H3 | n8n container has no healthcheck and no `depends_on` for backend | `compose:161-180` |
| I-H4 | Agents Dockerfile is single-stage -- build tools + Chromium bloat the production image (~1GB+) | `agents/Dockerfile` |
| I-H5 | Backend, agents, browser-worker, notifications Dockerfiles run as root (no `USER` directive) | All 4 Dockerfiles |
| I-H6 | Notifications service missing `.dockerignore` | `notifications/` |
| I-H7 | YouTube, TikTok, X env vars completely missing from `.env` -- those channels are unconfigured | `.env` vs `.env.example` |
| I-H8 | Agents config references `INSTAGRAM_ACCESS_TOKEN` but `.env` has `META_ACCESS_TOKEN` -- names don't match | `agents/config.py:59-61` vs `.env:80-84` |
| I-H9 | `FRONTEND_URL=http://localhost:3000` -- CORS blocks all browser requests in production | `.env:66` |
| I-H10 | MinIO image uses `:latest` tag -- non-reproducible builds | `compose:74` |

### Backend (10)

| ID | Issue | File |
|----|-------|------|
| B-H1 | `brands` table missing `website_url` column in `init.sql` (model has it) | `init.sql:28-45` vs `brand.py:51` |
| B-H2 | `brands.target_audience` defaults to `'[]'` (array) in SQL but `dict` in model | `init.sql:36` vs `brand.py:55` |
| B-H3 | 6 column size mismatches between `init.sql` and product model (VARCHAR(100) vs String(255), etc.) | `init.sql:56-72` vs `product.py` |
| B-H4 | `campaigns.objective` has SQL CHECK constraint but model accepts any string | `init.sql:98-101` vs `campaign.py:22` |
| B-H5 | `prompt_versions.a_b_group` SQL CHECK `('A','B')` but model allows String(255) | `init.sql:222` vs `prompt_version.py:35` |
| B-H6 | `publish_checker` sets status to `"published"` before n8n confirms success | `publish_checker.py:60` |
| B-H7 | `_log_job()` never calculates `duration_ms`; `started_at` only from DEFAULT | `morning_jobs.py:14` |
| B-H8 | Engagement puller ignores per-channel credentials (only reads `social_credentials`) | `engagement_puller.py:83` |
| B-H9 | `content.headline` VARCHAR(500) in SQL vs String(255) in model | `init.sql:163` vs `content.py:25` |
| B-H10 | Alembic `env.py` missing AI model imports -- can't generate migrations for those tables | `alembic/env.py` |

### Agents (9)

| ID | Issue | File |
|----|-------|------|
| A-H1 | No retry logic on any LLM/API call -- transient 429/500/503 kills entire workflow | `llm.py` (all functions) |
| A-H2 | `get_embedding()` and `generate_image()` have zero error handling (raw httpx exceptions) | `llm.py:173-229` |
| A-H3 | MinIO bucket creation race condition under concurrent workflows | `storage.py:30-35` |
| A-H4 | MinIO operations are synchronous -- block the asyncio event loop | `storage.py` (all functions) |
| A-H5 | Qdrant operations are synchronous -- block the asyncio event loop | `vector.py` (all functions) |
| A-H6 | Fabric `pyodbc` calls are synchronous in async function -- block event loop | `fabric.py:64-86` |
| A-H7 | No NATS dead-letter queue or `max_deliver` -- failing messages retry forever | `nats_consumer.py:51-56` |
| A-H8 | Fabric token cache never expires -- fails after ~60 min until worker restart | `fabric.py:20-41` |
| A-H9 | `MemorySaver` checkpointer for strategy/adaptation workflows -- state lost on restart | `strategy/graph.py:39`, `adaptation/graph.py:30` |

### Frontend (7)

| ID | Issue | File |
|----|-------|------|
| F-H1 | Unsafe `as unknown as` casts -- `ResearchReport[]` force-cast to `AgentRun[]` (different shapes) | `brands/[id]/page.tsx:227,247` |
| F-H2 | `useEffect` missing dependency `fetchApprovals` -- may use stale state | `approvals/page.tsx:17-19` |
| F-H3 | `useEffect` missing dependency `fetchEntries` + `searchQuery` | `system/audit/page.tsx:22-23` |
| F-H4 | `<img>` tags used instead of Next.js `<Image>` -- no optimization, no lazy loading | 6 components |
| F-H5 | `style jsx global` used without `styled-jsx` dependency (deprecated in App Router / Next 16) | `report/[id]/page.tsx:250` |
| F-H6 | No RBAC/role enforcement on frontend routes -- viewer can see admin panel | All page files |
| F-H7 | `brand.logo_url` rendered via `<img>` without protocol validation | `brands/[id]/page.tsx:693` |

---

## 3. MEDIUM Issues (47)

### Infrastructure (12)

| ID | Issue | File |
|----|-------|------|
| I-M1 | Traefik metrics entryPoint config inconsistent with Prometheus scrape target | `traefik.yml:53-54` vs `prometheus.yml:23-26` |
| I-M2 | Docker socket mounted to Traefik (even read-only = security vector) | `compose:20` |
| I-M3 | Grafana domain still `grafana.markai.example.com` | `grafana.ini:4` |
| I-M4 | Grafana references non-existent default dashboard JSON | `grafana.ini:21` |
| I-M5 | OTel traces pipeline only exports to "debug" -- traces discarded | `otel-collector-config.yaml:54-57` |
| I-M6 | Loki `auth_enabled: false` -- unauthenticated log access | `loki-config.yaml:1` |
| I-M7 | docker-compose.override.yml auto-loads in production if present (sets dev mode) | `.gitignore:27`, file exists |
| I-M8 | No resource limits (memory/CPU) on any Docker service | `compose` (all services) |
| I-M9 | All 17+ infrastructure ports exposed to host -- only 80/443 should be public | `compose` (all services) |
| I-M10 | LinkedIn workflow uses deprecated UGC API (`v2/ugcPosts`) | `linkedin-publish.json:112,194,229` |
| I-M11 | Qdrant healthcheck uses fragile bash TCP probe | `compose:64` |
| I-M12 | n8n env vars (`N8N_WEBHOOK_SECRET`, `MARKAI_API_URL`) not set in container environment | `compose` n8n service |

### Backend (14)

| ID | Issue | File |
|----|-------|------|
| B-M1 | `approvals.py` shadows `status` import from fastapi | `approvals.py:1,16` |
| B-M2 | SSE endpoint creates new DB session every 10s in `while True` loop | `notifications.py:64-86` |
| B-M3 | `datetime.now()` without timezone in 7+ files (DB columns are `TIMESTAMPTZ`) | Multiple files |
| B-M4 | `_call_llm` silently swallows LiteLLM errors with `except Exception: pass` | `intelligence.py:47-48` |
| B-M5 | `/api/v1/system/health` is unauthenticated but exposes infra connection status | `system.py:78-96` |
| B-M6 | Duplicate `upcoming` endpoints on content and calendar routers | `content.py:46-79`, `calendar.py:22-55` |
| B-M7 | `update_competitor` maps `notes` -> `description` but Competitor model has no `notes` attr | `brands.py:375-380` |
| B-M8 | `products.py` image gallery type inconsistency (list vs dict) | `products.py:232-234` |
| B-M9 | Platform credentials sent in plaintext to n8n webhook payload | `publish_service.py:162-163` |
| B-M10 | `validate_entra_token` calls synchronous JWKS fetch in async context -- blocks event loop | `entra.py:35` |
| B-M11 | `/api/v1/analytics/summary` has no brand_id filter -- returns combined metrics | `analytics.py:14-55` |
| B-M12 | Calendar reorder endpoint accepts unvalidated `list[dict]` -- no Pydantic model | `calendar.py:133-142` |
| B-M13 | `system.py` creates new Redis/Qdrant connections on every health check call | `system.py:237-298` |
| B-M14 | `ai_model_service.py` creates new Valkey connection per cache operation -- no pool | `ai_model_service.py:98-111` |

### Agents (11)

| ID | Issue | File |
|----|-------|------|
| A-M1 | `store_results` never calls `store_research()` -- function is dead code | `research/nodes.py:225-262` |
| A-M2 | `img.save(format="PNG", quality=95)` -- PNG ignores quality param (uses `compress_level`) | `image_processing.py:207,272` |
| A-M3 | Zero-size logo causes `ZeroDivisionError` in overlay | `image_processing.py:166` |
| A-M4 | `render_logo_png` fallback tries `Image.open()` on SVG -- Pillow can't open SVGs | `image_processing.py:81-93` |
| A-M5 | Temp file leak + filename collision risk in ImageMagick rendering | `image_processing.py:66-96` |
| A-M6 | LLM JSON parsing uses `.strip("```json")` which strips individual chars, not substring | 20+ occurrences across all workflows |
| A-M7 | `_auth_headers` caches LiteLLM key permanently -- no rotation support | `llm.py:41-45` |
| A-M8 | `upsert_product` ON CONFLICT (id) never fires -- creates duplicates instead of updating | `database.py:305-321` |
| A-M9 | Hashtags passed as Python list to SQL -- ambiguous column type handling | `database.py:273` |
| A-M10 | Content workflow continues after `load_context` returns `status: "failed"` -- wastes API calls | `content/graph.py:34-44` |
| A-M11 | Same issue in research, strategy, planning, evaluation workflows -- no early termination on failure | All workflow graphs |

### Frontend (10)

| ID | Issue | File |
|----|-------|------|
| F-M1 | `API_BASE_URL` duplicated in 3 files instead of shared constant | `api.ts:3`, `Header.tsx:22`, `content/[id]/page.tsx:91` |
| F-M2 | `BrandOnboarding` competitor discover loader checks wrong trigger value | `BrandOnboarding.tsx:347-349` |
| F-M3 | `CompetitorTracker` fetches same endpoint twice on mount | `CompetitorTracker.tsx:66-95` |
| F-M4 | Native `confirm()` used instead of accessible dialog for destructive actions | 2 components |
| F-M5 | CalendarView drag/drop missing ARIA attributes | `CalendarView.tsx:97-112` |
| F-M6 | Dialog `aria-describedby={undefined}` workaround for Radix warnings | `brands/[id]/page.tsx:853` |
| F-M7 | `Intl.supportedValuesOf` unsafe cast pattern | `settings/page.tsx:17` |
| F-M8 | Content calendar renders empty CalendarView AND empty state message simultaneously | `calendar/page.tsx:52-58` |
| F-M9 | `next-auth` v4 used with Next.js 16 / React 19 -- upgrade path is Auth.js v5 | `package.json:30-31` |
| F-M10 | SSE `onmessage` handler silently maps unknown shapes without validation | `Header.tsx:72-92` |

---

## 4. LOW Issues (45)

### Infrastructure (8)

| ID | Issue | File |
|----|-------|------|
| I-L1 | Engagement pull has no routing for TikTok/X -- falls through to YouTube node | `engagement-pull.json` |
| I-L2 | n8n workflows reference `$env.N8N_WEBHOOK_SECRET` not set in n8n container env | All n8n workflow JSONs |
| I-L3 | CSP header allows `unsafe-inline` and `unsafe-eval` for scripts | `security-headers.yml:15` |
| I-L4 | Grafana admin password defaults to `change-me-grafana` | `grafana.ini:9` |
| I-L5 | `agent_runs` table has mutable fields but no `updated_at` trigger | `init.sql:483-499` |
| I-L6 | No `.dockerignore` excludes `alembic/` from agents/browser-worker builds | Agents/browser-worker |
| I-L7 | Duplicate indexes on `users.email`, `users.entra_object_id`, `brands.slug` (UNIQUE already creates index) | `init.sql:12,23,31,47` |
| I-L8 | `tsconfig.tsbuildinfo` untracked but not in `.gitignore` | `frontend/tsconfig.tsbuildinfo` |

### Backend (14)

| ID | Issue | File |
|----|-------|------|
| B-L1 | Unused import `func` in `intelligence.py` | `intelligence.py:19` |
| B-L2 | Entra error details exposed to client | `users.py:64,96` |
| B-L3 | LiteLLM error details exposed to client | `providers.py:142` |
| B-L4 | AI error details exposed to client | `intelligence.py:515` |
| B-L5 | Batch image fetch has no rate limiting for DuckDuckGo | `products.py:267-318` |
| B-L6 | Chrome User-Agent impersonation in `gemini_service.py` | `gemini_service.py:59` |
| B-L7 | `router.py` has inline route logic (inconsistent pattern) | `router.py:56-78` |
| B-L8 | `qdrant_service.py` passes string IDs where `PointIdsList` expected | `qdrant_service.py:122-123` |
| B-L9 | File size validation happens after full read into memory | `brands.py:190-192` |
| B-L10 | Non-idiomatic `__aenter__`/`__aexit__` pattern in `ai_model_service.py` | `ai_model_service.py:366-432` |
| B-L11 | No `ON DELETE CASCADE` on several FK references | `init.sql` (5 FKs) |
| B-L12 | `content.ai_model` VARCHAR(100) in SQL vs String(255) in model | `init.sql:174` vs `content.py:36` |
| B-L13 | `campaigns.name` VARCHAR(500) in SQL vs String(255) in model | `init.sql:96` vs `campaign.py:20` |
| B-L14 | `users.email` VARCHAR(320) in SQL vs String(255) in model | `init.sql:12` vs `auth/models.py:18` |

### Agents (10)

| ID | Issue | File |
|----|-------|------|
| A-L1 | `ResearchState` missing `research_data` key used by `store_results` | `research/state.py` |
| A-L2 | Inconsistent import style (some top-level, some inline) | `worker.py` |
| A-L3 | DuckDuckGo HTML parsing relies on fragile regex | `web_search.py:45-78` |
| A-L4 | Instagram/Facebook Graph API version `v20.0` hardcoded | `social.py:15-17` |
| A-L5 | `_draw_avatar` hardcodes "H" letter (Healthspan-specific) | `image_processing.py:243` |
| A-L6 | `generate_mockup` defaults to `"healthspan.mu"` username | `image_processing.py:250-251` |
| A-L7 | Adaptation workflow `applied_changes` list replacement works by accident (sequential execution) | `adaptation/nodes.py:88,138` |
| A-L8 | Worker signal handling on Windows may not shut down cleanly | `worker.py:329-334` |
| A-L9 | `pyproject.toml` `worker*` pattern won't match `worker.py` (not a package) | `pyproject.toml:33` |
| A-L10 | No health check endpoint -- orchestrators can't detect stuck workers | `worker.py` |

### Frontend (13)

| ID | Issue | File |
|----|-------|------|
| F-L1 | Prompt Lab weight input fires API call on every keystroke (no debounce) | `prompts/page.tsx:226` |
| F-L2 | `parseInt()` without radix and NaN check | `prompts/page.tsx:226` |
| F-L3 | No `loading="lazy"` on `<img>` tags | 6 components |
| F-L4 | Prompt Lab page not in sidebar navigation -- unreachable | `Sidebar.tsx` |
| F-L5 | Product Images page not in sidebar navigation | `Sidebar.tsx` |
| F-L6 | `<video>` has no `preload` attribute -- may fetch entire file for thumbnail | `AssetPreview.tsx:20` |
| F-L7 | System page catches errors silently (no toast or error state) | `system/page.tsx:62` |
| F-L8 | Audit log page silently swallows errors | `system/audit/page.tsx:35` |
| F-L9 | `BrandForm` website URL validation allows `javascript:` protocol | `BrandForm.tsx:288-295` |
| F-L10 | Unused `@radix-ui/react-tooltip` dependency | `package.json:25` |
| F-L11 | `next.config.ts` image remote patterns use `*.hstgr.cloud` wildcard | `next.config.ts:22-24` |
| F-L12 | `tsconfig.json` uses `"jsx": "react-jsx"` instead of Next.js standard `"preserve"` | `tsconfig.json:18` |
| F-L13 | CalendarView renders redundant empty calendar grid when no items | `calendar/page.tsx:52-58` |

---

## 5. Recommended Priority Fix Order

### Phase 1: Production Blockers (fix before any deployment)

1. **Change all default secrets** (I-C1, B-C4) -- `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`, `SECRET_KEY`
2. **Set production URLs** (I-C2, I-H9) -- `NEXT_PUBLIC_API_URL`, `FRONTEND_URL`
3. **Configure n8n webhook** (I-C3, I-C4) -- `N8N_WEBHOOK_BASE`, `N8N_WEBHOOK_SECRET`
4. **Fix CORS** (B-C1, B-C2) -- Never use `*` with credentials, don't echo arbitrary Origin
5. **Fix field name mismatches** (A-C3, A-C4) -- `channel`/`platform`, `item_type`/`content_type`
6. **Fix NATS ack_wait** (A-C1) -- Increase to >= `WORKFLOW_TIMEOUT` or use `in_progress()` acks
7. **Fix agents Dockerfile** (A-C5, A-C6) -- COPY source before pip install, install msodbcsql17
8. **Add role check to settings endpoint** (B-C3)
9. **Add `website_url` to `brands` in init.sql** (B-H1)
10. **Remove secrets from `.env.local`** (F-C1) and rotate any that may have been committed

### Phase 2: Reliability (fix before real traffic)

11. Add retry logic to all LLM/API calls (A-H1, A-H2)
12. Fix evaluation/adaptation schema mismatch (A-C2)
13. Run MinIO/Qdrant/Fabric operations in thread executor (A-H4, A-H5, A-H6)
14. Add `max_deliver` and dead-letter to NATS (A-H7)
15. Fix Fabric token cache expiry (A-H8)
16. Fix publish_checker premature status update (B-H6)
17. Add Docker healthchecks to all services (I-H2, I-H3)
18. Reconcile all SQL/model column size mismatches (B-H3, B-H9, B-L12-14)
19. Add early termination on failed `load_context` in all workflows (A-M10, A-M11)
20. Fix SSE auth (F-C2) and "Mark All Read" (F-C3)

### Phase 3: Hardening (fix before public launch)

21. Restrict exposed ports to 80/443 only (I-M9)
22. Add Traefik dashboard auth (I-H1)
23. Add non-root USER to all Dockerfiles (I-H5)
24. Add Docker resource limits (I-M8)
25. Fix frontend RBAC route guards (F-H6)
26. Replace `MemorySaver` with persistent checkpointer (A-H9)
27. Add `.dockerignore` to notifications service (I-H6)
28. Configure YouTube/TikTok/X env vars (I-H7)
29. Fix agent social token env var names (I-H8)
30. Update LinkedIn workflow to Posts API (I-M10)

---

## 6. What's Working Well

- **TypeScript compilation passes** with 0 errors across 79 frontend files
- **No `dangerouslySetInnerHTML`**, `@ts-ignore`, `eslint-disable`, or `any` types in frontend
- **Database schema** is comprehensive with proper indexes, FK constraints, and trigger functions
- **Multi-model AI pipeline** (OpenAI scene gen -> Gemini product replacement -> Pillow branding) is well-architected
- **8-channel platform adaptation** with per-platform constraints is production-grade
- **NATS-based event-driven architecture** with idempotency guards is solid design
- **MinIO object storage** properly abstracted with bucket management
- **Observability stack** (Prometheus, Loki, OTel, Grafana) is in place and configured
- **SSO/Azure AD auth** flow with proper JWT validation and token forwarding

---

*Generated by 4 parallel audit agents covering backend (43 issues), agents (36 issues), frontend (33 issues), and infrastructure (35 issues). Total: 147 issues across ~200+ files.*
