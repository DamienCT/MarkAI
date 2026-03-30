# MARKAI Master Remediation Plan

**Generated:** 2026-03-30
**Source:** 14 audit artifacts (Phases 1-11)
**Auditor:** Claude Opus 4.6

---

## How to Use This Plan

Each finding has:
- **Finding ID** (e.g., SEC-001) — unique identifier
- **Severity** — CRITICAL / HIGH / MEDIUM / LOW
- **Source** — which audit phase identified it
- **File(s)** — affected files and lines
- **Current Behavior** — what happens now
- **Proposed Fix** — what to do
- **Status** — `[ ] NOT STARTED`

---

# PHASE A: CRITICAL SECURITY FIXES (Immediate)

## SEC-001: Hardcoded Traefik Dashboard Credentials
- **Severity:** CRITICAL
- **Source:** Phase 1 Infra (C-1), Phase 4 Security (I-9)
- **File(s):** `docker-compose.yml` line 30
- **Current Behavior:** Traefik dashboard basic-auth bcrypt hash is hardcoded in the compose file, committed to version control. Anyone with repo access can brute-force offline.
- **Proposed Fix:** Move basicauth users string to `.env` variable (`TRAEFIK_DASHBOARD_AUTH`). Reference via `${TRAEFIK_DASHBOARD_AUTH}`. Add placeholder to `.env.example`.
- **Status:** `[ ] NOT STARTED`

## SEC-002: Grafana Admin Password Uses Insecure Default
- **Severity:** CRITICAL
- **Source:** Phase 1 Infra (C-2)
- **File(s):** `observability/grafana/grafana.ini` line 9
- **Current Behavior:** `admin_password = ${GF_SECURITY_ADMIN_PASSWORD:change-me-grafana}`. Variable not in `.env.example` or `.env.vps.example`, so default is always used.
- **Proposed Fix:** Add `GF_SECURITY_ADMIN_PASSWORD` to `.env.example` and `.env.vps.example`. Pass as env var to Grafana service in compose.
- **Status:** `[ ] NOT STARTED`

## SEC-003: Unauthenticated File Proxy Endpoint
- **Severity:** CRITICAL
- **Source:** Phase 1 Backend (H2), Phase 4 Security (D-7), Phase 7 API (C2)
- **File(s):** `backend/app/api/v1/files.py` lines 20-52
- **Current Behavior:** `GET /api/v1/files/{file_path:path}` serves any MinIO file without authentication. Security-by-obscurity via UUID paths.
- **Proposed Fix:** Add authentication via `Depends(get_current_user)`, or implement signed URLs with TTL, or restrict to specific path prefixes.
- **Status:** `[ ] NOT STARTED`

## SEC-004: Access Tokens Exposed in Frontend API Responses
- **Severity:** CRITICAL
- **Source:** Phase 1 Frontend (C1), Phase 1 Backend (H5)
- **File(s):** `frontend/src/types/index.ts` lines 31-38; `backend/app/services/publish_service.py` lines 14-59; `backend/app/scheduler/engagement_puller.py` lines 82-98
- **Current Behavior:** Social platform API tokens (Meta, LinkedIn, TikTok, X) stored in `brand_guidelines` JSONB are included in `BrandResponse` serialization. `ChannelConfig` interface in frontend includes `access_token`, `api_key`, `refresh_token` fields rendered in `<Input>` elements.
- **Proposed Fix:** Backend: exclude `social_credentials` and `access_token` fields from `BrandResponse` serialization. Frontend: never store raw API keys in React state; use masked tokens (last 4 chars).
- **Status:** `[ ] NOT STARTED`

## SEC-005: SQL Injection Risk via Generic execute_query/execute_update
- **Severity:** CRITICAL
- **Source:** Phase 1 Agents (C1), Phase 6 Database (DB-C4)
- **File(s):** `agents/shared/tools/database.py` lines 517-531
- **Current Behavior:** `execute_query()` and `execute_update()` accept arbitrary raw SQL strings. While current callers use parameterized queries, any future caller using string interpolation would enable SQL injection.
- **Proposed Fix:** Restrict to parameterized queries only. Add an allowlist of query patterns, or replace with purpose-built DAO methods. Add code review gate prohibiting raw SQL construction outside `database.py`.
- **Status:** `[ ] NOT STARTED`

## SEC-006: No Rate Limiting Anywhere in the Stack
- **Severity:** CRITICAL
- **Source:** Phase 1 Backend (M3, M4), Phase 4 Security (N-4), Phase 7 API (C1)
- **File(s):** All API endpoints; no middleware configured
- **Current Behavior:** No rate limiting on any endpoint. AI generation endpoints (`/intelligence/generate-fields`, `/intelligence/rewrite-field`), file uploads, and auth endpoints are all unprotected.
- **Proposed Fix:** Add rate limiting at Traefik layer (middleware `rateLimit`) and/or in FastAPI using `slowapi`. Priority: LLM endpoints (10 req/min per user), file uploads, auth endpoints.
- **Status:** `[ ] NOT STARTED`

## SEC-007: Qdrant Has No Authentication
- **Severity:** CRITICAL
- **Source:** Phase 1 Infra (H-3), Phase 4 Security (I-5), Phase 3 AI (CRITICAL-1)
- **File(s):** `docker-compose.yml` lines 61-74; `backend/app/services/qdrant_service.py` line 29
- **Current Behavior:** Qdrant runs without any API key. Backend client creates connection without `api_key` parameter. Any container on the network can read/write/delete all vector data.
- **Proposed Fix:** Set `QDRANT__SERVICE__API_KEY` on Qdrant service. Add `api_key=settings.QDRANT_API_KEY` to backend QdrantClient constructor. Add `QDRANT_API_KEY` to `.env.example`.
- **Status:** `[ ] NOT STARTED`

## SEC-008: Valkey (Redis) Has No Authentication
- **Severity:** CRITICAL
- **Source:** Phase 1 Infra (H-6), Phase 4 Security (I-5)
- **File(s):** `docker-compose.yml` lines 97-110
- **Current Behavior:** Valkey runs without `--requirepass`. Any container on the network can access cache without authentication.
- **Proposed Fix:** Add `command: ["valkey-server", "--requirepass", "${VALKEY_PASSWORD}"]`. Update all consumers (LiteLLM, backend, agents) to provide password.
- **Status:** `[ ] NOT STARTED`

## SEC-009: NATS Has No Authentication
- **Severity:** CRITICAL
- **Source:** Phase 1 Infra (H-7), Phase 4 Security (I-5)
- **File(s):** `docker-compose.yml` lines 113-127
- **Current Behavior:** NATS runs with just `-js -m 8222`. No authentication. Any container on the network can publish/subscribe to any subject.
- **Proposed Fix:** Configure NATS authentication (token or nkey) and update all NATS clients.
- **Status:** `[ ] NOT STARTED`

## SEC-010: MinIO Credentials Use Weak Defaults
- **Severity:** HIGH
- **Source:** Phase 1 Infra (H-4)
- **File(s):** `docker-compose.yml` lines 82-83
- **Current Behavior:** `MINIO_ROOT_USER` defaults to `markai-minio`, `MINIO_ROOT_PASSWORD` defaults to `change-me`.
- **Proposed Fix:** Remove `:-` fallback defaults so service fails to start if credentials are not configured.
- **Status:** `[ ] NOT STARTED`

## SEC-011: PostgreSQL Password Has Weak Default
- **Severity:** HIGH
- **Source:** Phase 1 Infra (H-5)
- **File(s):** `docker-compose.yml` line 47
- **Current Behavior:** `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change-me}` provides a trivially guessable default.
- **Proposed Fix:** Remove the `:-change-me` default so service fails to start without explicit password.
- **Status:** `[ ] NOT STARTED`

## SEC-012: CSP Contains unsafe-inline and unsafe-eval
- **Severity:** HIGH
- **Source:** Phase 1 Infra (H-8), Phase 4 Security (N-2)
- **File(s):** `traefik/dynamic/security-headers.yml` line 15
- **Current Behavior:** Content Security Policy includes `'unsafe-inline'` and `'unsafe-eval'` for `script-src`, significantly weakening XSS protection.
- **Proposed Fix:** Use nonces or hashes for inline scripts. Remove `'unsafe-eval'` once confirmed the app works without it.
- **Status:** `[ ] NOT STARTED`

## SEC-013: Unauthenticated Logo Endpoint
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H9), Phase 7 API (C3), Phase 10 Code Quality
- **File(s):** `backend/app/api/v1/brands.py` lines 310-333
- **Current Behavior:** `GET /brands/{brand_id}/logos/{label}` has no `Depends(get_current_user)`. Anyone who knows brand_id and label can access logos.
- **Proposed Fix:** Add `current_user: User = Depends(get_current_user)` or document as intentionally public.
- **Status:** `[ ] NOT STARTED`

## SEC-014: No File Size/Type Validation on Product Image Upload
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H3), Phase 4 Security (N-5), Phase 7 API (H6)
- **File(s):** `backend/app/api/v1/products.py` lines 158-162
- **Current Behavior:** `upload_product_image` reads entire file into memory without checking content type or size. Malicious user could upload multi-GB file causing OOM.
- **Proposed Fix:** Add max file size check (5MB), content-type validation (image types only), and sanitize filename before MinIO path. Set global `--limit-max-request-size` on uvicorn.
- **Status:** `[ ] NOT STARTED`

## SEC-015: Missing Authorization on Brand Activation/Onboarding
- **Severity:** HIGH
- **Source:** Phase 7 API (C4)
- **File(s):** `backend/app/api/v1/brands.py` lines 123-200
- **Current Behavior:** `complete-onboarding` and `activate` endpoints require only **viewer** role. Any authenticated viewer can trigger expensive LLM agent chains.
- **Proposed Fix:** Both endpoints should require **manager** role minimum.
- **Status:** `[ ] NOT STARTED`

## SEC-016: litellm Supply-Chain Attack Risk (CVE-2026-33634)
- **Severity:** HIGH
- **Source:** Phase 2 Dependencies
- **File(s):** `backend/pyproject.toml`, `agents/pyproject.toml`
- **Current Behavior:** `litellm>=1.60` floor means pip could resolve to a compromised version (1.82.7-1.82.8 contained backdoor).
- **Proposed Fix:** Pin `litellm==1.82.6` in all pyproject.toml files. Audit installed environments for `litellm_init.pth`.
- **Status:** `[ ] NOT STARTED`

## SEC-017: Backend _call_llm Missing Prompt Sanitization
- **Severity:** HIGH
- **Source:** Phase 3 AI (HIGH-2)
- **File(s):** `backend/app/api/v1/intelligence.py` lines 509-568
- **Current Behavior:** Brand names, descriptions, and other user-editable fields are interpolated directly into LLM prompts without calling `sanitize_for_prompt()`.
- **Proposed Fix:** Import and apply `sanitize_for_prompt` from agents or replicate sanitization logic in backend.
- **Status:** `[ ] NOT STARTED`

## SEC-018: Unsanitized Filename in Product Image Upload
- **Severity:** MEDIUM
- **Source:** Phase 4 Security (I-12)
- **File(s):** `backend/app/api/v1/products.py` line 159
- **Current Behavior:** User-supplied filename used directly in MinIO object path without sanitization.
- **Proposed Fix:** Sanitize or replace filename with generated UUID + original extension.
- **Status:** `[ ] NOT STARTED`

## SEC-019: No Input Validation on limit Query Parameters
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (H4), Phase 5 Performance (B11), Phase 7 API (M2)
- **File(s):** Multiple API endpoints
- **Current Behavior:** Most list endpoints accept `limit` as integer with no upper bound. A user could pass `limit=999999`.
- **Proposed Fix:** Add `Query(le=500)` or `limit = min(limit, 200)` on all `limit` parameters.
- **Status:** `[ ] NOT STARTED`

## SEC-020: Content Status Transition Allows Arbitrary Values
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (H12)
- **File(s):** `backend/app/api/v1/content.py` lines 137-152
- **Current Behavior:** `new_status` taken as bare query parameter with no validation against allowed statuses.
- **Proposed Fix:** Validate `new_status in ALL_STATUSES`, restrict "queued" reset to managers/admins.
- **Status:** `[ ] NOT STARTED`

## SEC-021: Frontend Admin Pages Lack Role-Based Access Control
- **Severity:** HIGH
- **Source:** Phase 1 Frontend (H1)
- **File(s):** `src/app/settings/users/page.tsx`, `src/app/system/page.tsx`, `src/app/system/audit/page.tsx`, `src/app/settings/page.tsx`
- **Current Behavior:** Admin-sensitive pages do not call `useRequireRole()`. Any authenticated user can access them.
- **Proposed Fix:** Add `useRequireRole("admin")` or `useRequireRole("manager")` at top of each admin page.
- **Status:** `[ ] NOT STARTED`

## SEC-022: Duplicate Endpoints with Weaker Auth
- **Severity:** MEDIUM
- **Source:** Phase 7 API (H1, H2)
- **File(s):** `backend/app/api/v1/system.py` lines 323-337; `backend/app/api/router.py` lines 59-80
- **Current Behavior:** `/system/scheduler/jobs` (viewer) duplicates `/system/jobs` (manager). `/audit` (viewer) duplicates `/system/audit-log` (manager).
- **Proposed Fix:** Remove duplicate endpoints with weaker access control.
- **Status:** `[ ] NOT STARTED`

## SEC-023: n8n and Backend Ports Exposed on 0.0.0.0 in Dev
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (H-12)
- **File(s):** `docker-compose.override.yml` lines 40-45
- **Current Behavior:** n8n and backend ports bound to all interfaces, accessible from network.
- **Proposed Fix:** Change to `127.0.0.1:5678:5678` and `127.0.0.1:8000:8000`.
- **Status:** `[ ] NOT STARTED`

## SEC-024: SSRF Risk via DuckDuckGo Image Search
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M10)
- **File(s):** `backend/app/services/gemini_service.py` lines 43-152
- **Current Behavior:** Fetches arbitrary URLs from DuckDuckGo results with `follow_redirects=True`. Could redirect to internal services (cloud metadata).
- **Proposed Fix:** Validate fetched URLs are not internal/private IPs before downloading. Add URL blocklist.
- **Status:** `[ ] NOT STARTED`

---

# PHASE B: CRITICAL BUG FIXES (Immediate)

## BUG-001: get_performance_data References Non-Existent Column measured_at
- **Severity:** CRITICAL
- **Source:** Phase 6 Database (DB-C1)
- **File(s):** `agents/shared/tools/database.py` lines 429-430
- **Current Behavior:** Query references `em.measured_at` but `engagement_metrics` table has `fetched_at`. Query crashes at runtime.
- **Proposed Fix:** Change `em.measured_at` to `em.fetched_at`.
- **Status:** `[ ] NOT STARTED`

## BUG-002: store_adaptations Inserts Into Non-Existent Columns
- **Severity:** CRITICAL
- **Source:** Phase 6 Database (DB-C2)
- **File(s):** `agents/shared/tools/database.py` lines 452-468
- **Current Behavior:** Evaluation-node branch inserts `brand_id`, `tier`, `confidence`, `data` columns that do not exist on the `adaptations` table. Crashes at runtime.
- **Proposed Fix:** Rewrite to use the correct column names from the `adaptations` table schema.
- **Status:** `[ ] NOT STARTED`

## BUG-003: upsert_product ON CONFLICT on Non-Existent Unique Constraint
- **Severity:** CRITICAL
- **Source:** Phase 6 Database (DB-C3)
- **File(s):** `agents/shared/tools/database.py` lines 310-323; `db/init.sql` products table
- **Current Behavior:** `ON CONFLICT (brand_id, bc_item_no)` but no unique constraint exists on those columns. Query crashes at runtime.
- **Proposed Fix:** Add `UNIQUE(brand_id, bc_item_no) WHERE bc_item_no IS NOT NULL` to products table. Or create a partial unique index.
- **Status:** `[ ] NOT STARTED`

## BUG-004: MemorySaver Checkpointer Causes Unbounded Memory Growth (OOM)
- **Severity:** CRITICAL
- **Source:** Phase 1 Agents (C3)
- **File(s):** `agents/workflows/strategy/graph.py` line 45; `agents/workflows/adaptation/graph.py` line 35
- **Current Behavior:** `MemorySaver()` stores all checkpoint state in-memory. Never cleaned up. Will OOM in production under load.
- **Proposed Fix:** Replace with `AsyncPostgresSaver` from `langgraph-checkpoint-postgres` using existing Postgres database.
- **Status:** `[ ] NOT STARTED`

## BUG-005: Unbounded LLM Output Trusted Without Schema Validation
- **Severity:** CRITICAL
- **Source:** Phase 1 Agents (C2)
- **File(s):** `agents/workflows/planning/nodes.py` lines 237-239; `agents/workflows/content/nodes.py` lines 367-370
- **Current Behavior:** LLM-generated JSON parsed via `parse_llm_json()` then used directly for database records without schema validation. Unexpected types can cause unhandled exceptions or corrupt data.
- **Proposed Fix:** Add Pydantic models between `parse_llm_json()` and all database operations. Validate field types, lengths, and allowed values.
- **Status:** `[ ] NOT STARTED`

## BUG-006: Race Condition in Idempotency Check (TOCTOU)
- **Severity:** CRITICAL
- **Source:** Phase 1 Agents (C4)
- **File(s):** `agents/worker.py` lines 121-136
- **Current Behavior:** Duplicate workflow check and `create_agent_run()` are not atomic. Two NATS messages can both pass the check. `pass` on exception silently ignores failures.
- **Proposed Fix:** Use DB-level unique constraint or advisory lock. `INSERT ... ON CONFLICT DO NOTHING` with partial unique index on `(brand_id, agent_type) WHERE status = 'running'`.
- **Status:** `[ ] NOT STARTED`

## BUG-007: Adaptation Workflow get_pending_adaptations Queries Wrong Schema
- **Severity:** CRITICAL
- **Source:** Phase 1 Agents (C5)
- **File(s):** `agents/shared/tools/database.py` lines 492-503
- **Current Behavior:** `get_pending_adaptations()` JOINs on `source_content_id` but evaluation-generated adaptations use `brand_id` directly with no `source_content_id`. Those records are never returned, making adaptation workflow a no-op for evaluation-generated adaptations.
- **Proposed Fix:** Rewrite query to handle both schemas using UNION or broader WHERE clause.
- **Status:** `[ ] NOT STARTED`

## BUG-008: _extract_month_section Regex ValueError
- **Severity:** HIGH
- **Source:** Phase 1 Agents (M10)
- **File(s):** `agents/workflows/content/nodes.py` lines 43-56
- **Current Behavior:** `rf"(#{1,3}\s*..."` — in raw f-string, `{1,3}` is a Python expression, not regex. Raises `ValueError`.
- **Proposed Fix:** Change to `rf"(#{{1,3}}\s*..."` to produce literal `{1,3}` in regex.
- **Status:** `[ ] NOT STARTED`

## BUG-009: Missing flag_modified for JSONB Update in Webhooks
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H11)
- **File(s):** `backend/app/api/v1/webhooks.py` lines 95-97
- **Current Behavior:** JSONB mutation in-place without `flag_modified`. SQLAlchemy may not detect the change; error may silently not persist.
- **Proposed Fix:** Add `flag_modified(content, "generation_metadata")` after the update.
- **Status:** `[ ] NOT STARTED`

## BUG-010: Content Nodes Gemini Uses Wrong Model Category
- **Severity:** HIGH
- **Source:** Phase 3 AI (HIGH-5)
- **File(s):** `agents/workflows/content/nodes.py` line 678
- **Current Behavior:** `get_model_for_category("vision")` returns OpenAI model string, but this is passed to Gemini client. Gemini client will fail or ignore.
- **Proposed Fix:** Use hardcoded Gemini model names from `gemini_service.py` or create a separate "gemini-image" category.
- **Status:** `[ ] NOT STARTED`

## BUG-011: strategy/nodes.py research_data May Be String Instead of Dict
- **Severity:** HIGH
- **Source:** Phase 1 Agents (H12)
- **File(s):** `agents/workflows/strategy/nodes.py` lines 22-25
- **Current Behavior:** `output_payload` may be a JSON string depending on driver behavior. Subsequent `.get()` calls will fail.
- **Proposed Fix:** Parse through `_parse_payload()` before returning.
- **Status:** `[ ] NOT STARTED`

## BUG-012: ContentState TypedDict Missing Fields Used by Nodes
- **Severity:** HIGH
- **Source:** Phase 1 Agents (H13)
- **File(s):** `agents/workflows/content/state.py`; `agents/workflows/content/nodes.py` lines 133-144
- **Current Behavior:** `load_context` returns keys not in `ContentState` TypedDict. Undeclared keys may be silently dropped depending on LangGraph version.
- **Proposed Fix:** Add all fields (`positioning`, `relevant_pillar`, `relevant_audience`, `month_context`, `recent_posts`, `top_performing`, `product`) to `ContentState`.
- **Status:** `[ ] NOT STARTED`

## BUG-013: Race Condition in Graph Token Cache
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H6)
- **File(s):** `backend/app/auth/entra.py` lines 73-81
- **Current Behavior:** `_graph_token_lock` created lazily — TOCTOU race if two coroutines call before lock is created.
- **Proposed Fix:** Initialize `_graph_token_lock` at module level.
- **Status:** `[ ] NOT STARTED`

## BUG-014: GEMINI_API_KEY Missing from .env.example and LiteLLM Config
- **Severity:** HIGH
- **Source:** Phase 1 Infra (C-3)
- **File(s):** `.env.example`, `litellm/config.yaml`, `docker-compose.yml`
- **Current Behavior:** Gemini models only accessible via direct API calls, bypassing LiteLLM proxy gateway.
- **Proposed Fix:** Add `GEMINI_API_KEY` to `.env.example`. Add Gemini model entries to `litellm/config.yaml`. Pass to LiteLLM service.
- **Status:** `[ ] NOT STARTED`

## BUG-015: Worker Chain Error Overwrites Successful Result
- **Severity:** HIGH
- **Source:** Phase 1 Agents (H8)
- **File(s):** `agents/worker.py` lines 314-322
- **Current Behavior:** If chain publish fails after workflow succeeds, `complete_agent_run()` is called again, overwriting the successful result.
- **Proposed Fix:** Use a separate update to append chain error metadata instead of calling `complete_agent_run()` again.
- **Status:** `[ ] NOT STARTED`

## BUG-016: get_pending_adaptations Misses auto_applied Status
- **Severity:** HIGH
- **Source:** Phase 1 Agents (H10)
- **File(s):** `agents/shared/tools/database.py` lines 492-503
- **Current Behavior:** Evaluation sets tier1 to `status: "auto_applied"`, but `get_pending_adaptations()` only queries `status = 'proposed'`.
- **Proposed Fix:** Include `status = 'auto_applied'` in the query.
- **Status:** `[ ] NOT STARTED`

## BUG-017: Inconsistent Transaction in update_brand
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M7), Phase 5 Performance (D12)
- **File(s):** `backend/app/api/v1/brands.py` lines 99-120
- **Current Behavior:** Brand update and agent_runs cancellation are separate transactions. If second fails, brand is deactivated but agents are not cancelled.
- **Proposed Fix:** Wrap both operations in a single transaction.
- **Status:** `[ ] NOT STARTED`

---

# PHASE C: HIGH-SEVERITY FIXES

## PERF-001: Blocking Synchronous I/O in fabric_service.py
- **Severity:** CRITICAL
- **Source:** Phase 1 Backend (C1), Phase 5 Performance (B22)
- **File(s):** `backend/app/services/fabric_service.py` lines 79-100
- **Current Behavior:** `pyodbc.connect()`, `cursor.execute()`, `cursor.fetchall()` are blocking synchronous calls inside `async def`. Blocks entire asyncio event loop during every Fabric SQL query.
- **Proposed Fix:** Wrap in `asyncio.to_thread()` or use `aioodbc`.
- **Status:** `[ ] NOT STARTED`

## PERF-002: Blocking Synchronous I/O in minio_service.py
- **Severity:** HIGH
- **Source:** Phase 1 Backend (C2), Phase 5 Performance (B23)
- **File(s):** `backend/app/services/minio_service.py` all functions
- **Current Behavior:** All MinIO operations are synchronous blocking calls via `minio` SDK, called from async handlers. Blocks event loop on every file upload/download.
- **Proposed Fix:** Wrap all MinIO calls in `asyncio.to_thread()` or create async wrapper functions.
- **Status:** `[ ] NOT STARTED`

## PERF-003: Blocking Synchronous I/O in qdrant_service.py
- **Severity:** HIGH
- **Source:** Phase 1 Backend (C3), Phase 5 Performance (B24)
- **File(s):** `backend/app/services/qdrant_service.py` all functions
- **Current Behavior:** `QdrantClient` is synchronous. All operations block the event loop.
- **Proposed Fix:** Replace with `AsyncQdrantClient` from `qdrant_client` or wrap in `asyncio.to_thread()`.
- **Status:** `[ ] NOT STARTED`

## PERF-004: JWT JWKS Fetch Is Synchronous
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H1)
- **File(s):** `backend/app/auth/entra.py` line 35
- **Current Behavior:** `client.get_signing_key_from_jwt(token)` is synchronous HTTP request that blocks event loop on first call or cache miss.
- **Proposed Fix:** Use `await asyncio.to_thread(client.get_signing_key_from_jwt, token)`.
- **Status:** `[ ] NOT STARTED`

## PERF-005: httpx.AsyncClient Created Per-Request
- **Severity:** HIGH
- **Source:** Phase 1 Agents (H3)
- **File(s):** `agents/shared/llm.py` lines 167, 204, 242; `agents/shared/tools/browser.py`; `agents/shared/tools/social.py`; `agents/shared/tools/fabric.py`
- **Current Behavior:** Every LLM/embedding/image call creates a new `httpx.AsyncClient`, adding ~50-100ms per request from TLS handshake overhead.
- **Proposed Fix:** Create module-level `httpx.AsyncClient` instances with connection pooling. Ensure proper cleanup on shutdown.
- **Status:** `[ ] NOT STARTED`

## PERF-006: No Connection Pooling for Fabric SQL
- **Severity:** HIGH
- **Source:** Phase 5 Performance (B14)
- **File(s):** `backend/app/services/fabric_service.py` lines 64-76
- **Current Behavior:** Creates a new pyodbc connection for every query. No connection pooling.
- **Proposed Fix:** Use connection pool or cache connection with TTL matching token lifetime.
- **Status:** `[ ] NOT STARTED`

## VAL-001: No Pydantic Enum Validation on Any Schema
- **Severity:** HIGH
- **Source:** Phase 6 Database (DB-H2)
- **File(s):** `backend/app/schemas/*.py`
- **Current Behavior:** Pydantic schemas do not validate enum/CHECK values for `status`, `channel`, `item_type`, etc. Invalid values pass API validation and fail at DB commit with cryptic `IntegrityError`.
- **Proposed Fix:** Add `Literal` type annotations or Pydantic validators for all enum fields.
- **Status:** `[ ] NOT STARTED`

## VAL-002: Settings PUT Accepts Untyped dict
- **Severity:** MEDIUM
- **Source:** Phase 7 API (H5)
- **File(s):** `backend/app/api/v1/settings.py` line 27
- **Current Behavior:** `PUT /settings/` accepts bare `dict` with no Pydantic schema validation.
- **Proposed Fix:** Add a Pydantic schema for settings update.
- **Status:** `[ ] NOT STARTED`

## VAL-003: No Pagination on Graph API Group Members
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H7)
- **File(s):** `backend/app/api/v1/users.py` lines 153-184
- **Current Behavior:** `get_security_group_members` fetches with `$top=999` but does not handle `@odata.nextLink`. Silently truncated if >999 members.
- **Proposed Fix:** Implement pagination loop following `@odata.nextLink`.
- **Status:** `[ ] NOT STARTED`

## VAL-004: get_graph_users_by_ids Unbounded Filter List
- **Severity:** HIGH
- **Source:** Phase 1 Backend (H8)
- **File(s):** `backend/app/auth/entra.py` lines 160-186
- **Current Behavior:** OData `$filter` with `id in (...)` containing all IDs. Graph API has `in` operator limit of ~15 values.
- **Proposed Fix:** Batch IDs into chunks of 15 and make multiple calls.
- **Status:** `[ ] NOT STARTED`

## MISC-001: LiteLLM Uses Floating Tag main-latest
- **Severity:** HIGH
- **Source:** Phase 1 Infra (H-9), Phase 3 AI (CRITICAL-2)
- **File(s):** `docker-compose.yml` line 131
- **Current Behavior:** `ghcr.io/berriai/litellm:main-latest` changes with every push to main. Can introduce breaking changes silently.
- **Proposed Fix:** Pin to a specific version tag (e.g., `v1.65.5`).
- **Status:** `[ ] NOT STARTED`

## MISC-002: Token Usage Not Tracked
- **Severity:** HIGH
- **Source:** Phase 3 AI (CRITICAL-3)
- **File(s):** `agents/shared/llm.py`; `agent_runs` schema
- **Current Behavior:** `chat_completion()` returns only content, discards `usage` data. `tokens_used` and `cost_usd` columns exist but are never populated.
- **Proposed Fix:** Extract token usage from LiteLLM response and propagate to `agent_runs`.
- **Status:** `[ ] NOT STARTED`

## MISC-003: Backend _call_llm Has No Retry Logic
- **Severity:** HIGH
- **Source:** Phase 3 AI (HIGH-1)
- **File(s):** `backend/app/api/v1/intelligence.py` lines 24-69
- **Current Behavior:** Transient API failures (429, 502) immediately error out brand field generation.
- **Proposed Fix:** Add tenacity retry decorator matching the pattern in `agents/shared/llm.py`.
- **Status:** `[ ] NOT STARTED`

## MISC-004: No response_format for JSON Outputs
- **Severity:** HIGH
- **Source:** Phase 3 AI (HIGH-4)
- **File(s):** All workflow nodes
- **Current Behavior:** Prompts request JSON via natural language rather than using `response_format={"type": "json_object"}`.
- **Proposed Fix:** Pass `response_format={"type": "json_object"}` for all calls expecting JSON output.
- **Status:** `[ ] NOT STARTED`

## MISC-005: No CI/CD Pipeline
- **Severity:** HIGH
- **Source:** Phase 9 Infrastructure (I9-11)
- **File(s):** No `.github/workflows/`, no `Makefile`
- **Current Behavior:** Deployments are entirely manual. No automated linting, testing, building, or deployment.
- **Proposed Fix:** Create minimal GitHub Actions workflow: lint + type-check + tests on PR; build Docker images on merge; weekly dependency scan.
- **Status:** `[ ] NOT STARTED`

## MISC-006: Zero Automated Tests
- **Severity:** HIGH
- **Source:** Phase 10 Code Quality, Phase 11 Documentation
- **File(s):** Entire codebase
- **Current Behavior:** Zero test files anywhere. 208 source files with 0% test coverage. pytest is a dev dependency but never used.
- **Proposed Fix:** Add smoke tests for API endpoints, integration tests for auth flow, content transitions, LLM parsing, and NATS handling.
- **Status:** `[ ] NOT STARTED`

---

# PHASE D: DATABASE & SCHEMA FIXES

## DB-001: Alembic Versions Directory Is Empty
- **Severity:** HIGH
- **Source:** Phase 1 Infra (H-11), Phase 6 Database (DB-H1), Phase 10 Code Quality
- **File(s):** `backend/alembic/versions/` (empty)
- **Current Behavior:** No migration files. Schema managed by `db/init.sql` only. No migration history, rollback, or incremental evolution.
- **Proposed Fix:** Generate initial Alembic migration from current schema. Use migrations for all future changes.
- **Status:** `[ ] NOT STARTED`

## DB-002: Missing Unique Constraint on (brand_id, bc_item_no)
- **Severity:** HIGH
- **Source:** Phase 6 Database (DB-H3)
- **File(s):** `db/init.sql` products table
- **Current Behavior:** No unique constraint. BC sync can create duplicate products. `upsert_product` ON CONFLICT clause crashes.
- **Proposed Fix:** `ALTER TABLE products ADD CONSTRAINT uq_products_brand_bc UNIQUE(brand_id, bc_item_no) WHERE bc_item_no IS NOT NULL;`
- **Status:** `[ ] NOT STARTED`

## DB-003: Missing Composite Index on engagement_metrics
- **Severity:** HIGH
- **Source:** Phase 5 Performance (D1)
- **File(s):** `db/init.sql` engagement_metrics table
- **Current Behavior:** No composite index on `(brand_id, fetched_at)`. Analytics queries do full-table scans.
- **Proposed Fix:** `CREATE INDEX idx_engagement_metrics_brand_fetched ON engagement_metrics (brand_id, fetched_at DESC);`
- **Status:** `[ ] NOT STARTED`

## DB-004: Missing NOT NULL on Timestamp Columns
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (M-14, M-15, M-16)
- **File(s):** `db/init.sql` — `app_settings.updated_at`, `ai_model_categories.created_at`, `ai_model_selections.set_at`, `ai_models.discovered_at`
- **Current Behavior:** These `TIMESTAMPTZ DEFAULT NOW()` columns lack `NOT NULL`, inconsistent with all other tables.
- **Proposed Fix:** Add `NOT NULL` constraints.
- **Status:** `[ ] NOT STARTED`

## DB-005: Missing CHECK Constraint on engagement_metrics.channel
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (L-11)
- **File(s):** `db/init.sql` line 281
- **Current Behavior:** `channel VARCHAR(50) NOT NULL` lacks CHECK constraint unlike other channel columns.
- **Proposed Fix:** Add `CHECK (channel IN ('instagram', 'facebook', 'linkedin', 'youtube', 'tiktok', 'x', 'website_blog', 'teams'))`.
- **Status:** `[ ] NOT STARTED`

## DB-006: Missing Composite Indexes
- **Severity:** MEDIUM
- **Source:** Phase 5 Performance (D2, D3, D4)
- **File(s):** `db/init.sql`
- **Current Behavior:** Missing indexes on: `engagement_metrics(calendar_item_id, content_id)`, `calendar_items(status, published_at)` partial, `agent_runs(brand_id, agent_type, created_at)`.
- **Proposed Fix:** Create the three composite indexes.
- **Status:** `[ ] NOT STARTED`

## DB-007: Numeric Precision Not Specified in ORM Models
- **Severity:** MEDIUM
- **Source:** Phase 6 Database (DB-M4)
- **File(s):** `backend/app/models/agent_run.py`, `backend/app/models/engagement.py`, `backend/app/models/prompt_version.py`
- **Current Behavior:** `Numeric` columns without precision specification (`cost_usd`, `engagement_rate`, `sentiment_score`, `performance_score`).
- **Proposed Fix:** Align ORM column types with SQL schema precision (e.g., `Numeric(10,6)` for cost_usd).
- **Status:** `[ ] NOT STARTED`

## DB-008: Missing Partial Unique Index for Current Content
- **Severity:** MEDIUM
- **Source:** Phase 6 Database (DB-M7)
- **File(s):** `db/init.sql` content table
- **Current Behavior:** Business rule "one current content per calendar item" enforced only in application code.
- **Proposed Fix:** `CREATE UNIQUE INDEX ON content (calendar_item_id) WHERE is_current = true;`
- **Status:** `[ ] NOT STARTED`

## DB-009: app_settings Has No SQLAlchemy Model
- **Severity:** LOW
- **Source:** Phase 1 Backend (M14), Phase 6 Database (DB-L1)
- **File(s):** `backend/app/api/v1/settings.py`, `backend/app/scheduler/__init__.py`, `backend/app/api/v1/intelligence.py`
- **Current Behavior:** `app_settings` table queried via raw SQL only. No SQLAlchemy model, not managed by Alembic.
- **Proposed Fix:** Create `AppSetting` model and register in `__init__.py`.
- **Status:** `[ ] NOT STARTED`

## DB-010: Mixed UUID Generation Functions
- **Severity:** LOW
- **Source:** Phase 1 Infra (M-17)
- **File(s):** `db/init.sql`
- **Current Behavior:** Older tables use `uuid_generate_v4()`, newer tables use `gen_random_uuid()`.
- **Proposed Fix:** Standardize on `gen_random_uuid()` across all tables.
- **Status:** `[ ] NOT STARTED`

---

# PHASE E: PERFORMANCE FIXES

## PERF-010: 8 Sequential DB Queries in Analytics Summary
- **Severity:** HIGH
- **Source:** Phase 5 Performance (B1)
- **File(s):** `backend/app/api/v1/analytics.py` lines 14-55
- **Current Behavior:** 8 separate SELECT queries for each metric. Full-table aggregation with no brand_id or date range filter.
- **Proposed Fix:** Combine into single query with conditional aggregation. Add date range filter. Cache in Valkey with 5-15 min TTL.
- **Status:** `[ ] NOT STARTED`

## PERF-011: 6 Sequential COUNT Queries in Dashboard Stats
- **Severity:** HIGH
- **Source:** Phase 5 Performance (B2)
- **File(s):** `backend/app/api/v1/dashboard.py` lines 11-48
- **Current Behavior:** 6 separate COUNT(*) queries per page load.
- **Proposed Fix:** Combine into single query using UNION ALL or `COUNT(*) FILTER`. Cache in Valkey with 2-5 min TTL.
- **Status:** `[ ] NOT STARTED`

## PERF-012: Full JSONB output_payload in List Endpoints
- **Severity:** HIGH
- **Source:** Phase 5 Performance (B10)
- **File(s):** `backend/app/api/v1/intelligence.py` lines 74-169
- **Current Behavior:** Agent runs list returns full `output_payload` JSONB (strategy documents, multi-page markdown).
- **Proposed Fix:** Exclude `output_payload` from list response. Return full payload only in detail endpoint.
- **Status:** `[ ] NOT STARTED`

## PERF-013: No Caching on Analytics/Dashboard Endpoints
- **Severity:** HIGH
- **Source:** Phase 5 Performance (B17, B18)
- **File(s):** `backend/app/api/v1/analytics.py`, `backend/app/api/v1/dashboard.py`
- **Current Behavior:** Full-table scans on every request. Analytics data changes only when engagement metrics are pulled (every 6 hours).
- **Proposed Fix:** Cache in Valkey with 5-15 min TTL for analytics, 2-5 min for dashboard.
- **Status:** `[ ] NOT STARTED`

## PERF-014: Per-Row Commit During BC Product Sync
- **Severity:** HIGH
- **Source:** Phase 5 Performance (D13)
- **File(s):** `backend/app/services/product_service.py` lines 71-91
- **Current Behavior:** Commits after every single product upsert. 500 products = 500 commits.
- **Proposed Fix:** Batch commits every 50-100 items.
- **Status:** `[ ] NOT STARTED`

## PERF-015: Next.js Image Optimization Disabled
- **Severity:** HIGH
- **Source:** Phase 5 Performance (F12)
- **File(s):** `frontend/next.config.ts` lines 5-13
- **Current Behavior:** `images.unoptimized: true` disables all image optimization. No resizing, WebP conversion, or lazy loading.
- **Proposed Fix:** Remove `unoptimized: true`. Configure `remotePatterns`. Use `<Image>` component.
- **Status:** `[ ] NOT STARTED`

## PERF-016: Missing Resource Limits on 12 Services
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (H-2), Phase 9 Infrastructure (I9-05)
- **File(s):** `docker-compose.yml`
- **Current Behavior:** No memory limits on traefik, qdrant, minio, valkey, nats, n8n, browser-worker, notifications, grafana, prometheus, loki, otel-collector.
- **Proposed Fix:** Add `deploy.resources.limits.memory` to all services.
- **Status:** `[ ] NOT STARTED`

## PERF-017: N+1 Queries in calendar_service reorder and list_categories
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M6), Phase 5 Performance (B3, B5)
- **File(s):** `backend/app/services/calendar_service.py` lines 96-116; `backend/app/services/ai_model_service.py` lines 450-486
- **Current Behavior:** Individual queries per item in loops.
- **Proposed Fix:** Fetch all items in single `WHERE id IN (...)` query. Use LEFT JOIN for categories.
- **Status:** `[ ] NOT STARTED`

## PERF-018: Sequential Batch Image Fetch
- **Severity:** MEDIUM
- **Source:** Phase 5 Performance (B6)
- **File(s):** `backend/app/api/v1/products.py` lines 275-325
- **Current Behavior:** Sequential product processing, each involving network I/O.
- **Proposed Fix:** Use `asyncio.gather()` with semaphore-guarded concurrency (3-5 concurrent).
- **Status:** `[ ] NOT STARTED`

## PERF-019: Valkey Connection Created Per Health Check
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M16), Phase 5 Performance (B15)
- **File(s):** `backend/app/api/v1/system.py` lines 44-54, 250-261
- **Current Behavior:** New `redis.Redis` connection every health check instead of using shared pool.
- **Proposed Fix:** Reuse existing Valkey connection pool from `ai_model_service`.
- **Status:** `[ ] NOT STARTED`

## PERF-020: Recharts/dnd-kit Imported Eagerly
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (H10), Phase 5 Performance (F7, F8)
- **File(s):** `src/components/analytics/EngagementChart.tsx`, `src/components/content/KanbanBoard.tsx`
- **Current Behavior:** Large libraries (~300KB recharts) loaded in main bundle. Only used on specific pages.
- **Proposed Fix:** Use `next/dynamic` to dynamically import these components.
- **Status:** `[ ] NOT STARTED`

## PERF-021: KanbanBoard/CalendarView Inline Filtering
- **Severity:** MEDIUM
- **Source:** Phase 5 Performance (F1, F2)
- **File(s):** `src/components/content/KanbanBoard.tsx` lines 166-196; `src/components/content/CalendarView.tsx` lines 99-107
- **Current Behavior:** 9 filter passes per render in Kanban, 30+ filter passes in Calendar.
- **Proposed Fix:** Memoize with `useMemo()` — single pass to build lookup maps.
- **Status:** `[ ] NOT STARTED`

## PERF-022: SSE Notification Polling Does Not Scale
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (H10), Phase 5 Performance (F19)
- **File(s):** `backend/app/api/v1/notifications.py` lines 57-96
- **Current Behavior:** Creates new DB session every 10 seconds per connected user. Many concurrent SSE connections can exhaust connection pool.
- **Proposed Fix:** Add per-user connection limits, maximum SSE lifetime, or use pub/sub (Valkey/NATS) instead of polling.
- **Status:** `[ ] NOT STARTED`

## PERF-023: Sequential Product Image Sourcing in Agents
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (H6, H7)
- **File(s):** `agents/workflows/product_intel/nodes.py` lines 73-186
- **Current Behavior:** Sequential image sourcing and brand research in for-loops. 500 products could take hours.
- **Proposed Fix:** Use `asyncio.gather()` with semaphore (10 concurrent).
- **Status:** `[ ] NOT STARTED`

## PERF-024: Sequential Embedding in Research store_results
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M19)
- **File(s):** `agents/workflows/research/nodes.py` lines 298-300
- **Current Behavior:** Sequential embedding API calls per text.
- **Proposed Fix:** Use `asyncio.gather()` or batch embedding API call.
- **Status:** `[ ] NOT STARTED`

## PERF-025: No Cache Headers on Brand Logo Serving
- **Severity:** MEDIUM
- **Source:** Phase 5 Performance (B21)
- **File(s):** `backend/app/api/v1/brands.py` lines 310-333
- **Current Behavior:** No `Cache-Control` header. Every logo request hits MinIO.
- **Proposed Fix:** Add `Cache-Control: public, max-age=86400`.
- **Status:** `[ ] NOT STARTED`

---

# PHASE F: MEDIUM-SEVERITY FIXES

## FIX-001: Hardcoded Fallback API URL in Frontend
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (H3)
- **File(s):** `src/lib/api.ts` line 4
- **Current Behavior:** Fallback `https://api.markai.srv1191974.hstgr.cloud` used if env var missing. Dev/staging can accidentally hit production.
- **Proposed Fix:** Use `localhost:8000` as dev fallback. Only use production URL in Dockerfile build arg.
- **Status:** `[ ] NOT STARTED`

## FIX-002: Frontend Dockerfile Default Build Arg Leaks Production URL
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (M-13)
- **File(s):** `frontend/Dockerfile` line 20
- **Current Behavior:** `ARG NEXT_PUBLIC_API_URL=https://api.markai.srv1191974.hstgr.cloud` hardcodes production domain.
- **Proposed Fix:** Change default to `http://localhost:8000` or remove default.
- **Status:** `[ ] NOT STARTED`

## FIX-003: Multiple Polling Intervals Without Coordination
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (H5), Phase 8 UX (M10)
- **File(s):** `src/app/brands/[id]/page.tsx` lines 238-296; `src/components/layout/Header.tsx`
- **Current Behavior:** Up to 3 concurrent polling intervals plus header notification poll. Async callbacks can overlap.
- **Proposed Fix:** Use single polling manager or add guard flag for overlapping requests.
- **Status:** `[ ] NOT STARTED`

## FIX-004: Missing AbortController Cleanup on Several Pages
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (M3)
- **File(s):** `src/app/page.tsx`, `src/app/analytics/page.tsx`, `src/app/intelligence/page.tsx`, `src/app/learning/page.tsx`
- **Current Behavior:** Fetch data in `useEffect` without aborting on unmount.
- **Proposed Fix:** Add AbortController pattern.
- **Status:** `[ ] NOT STARTED`

## FIX-005: ConfirmDialog Closes Before Async onConfirm Completes
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (M4)
- **File(s):** `src/components/ui/confirm-dialog.tsx` lines 46-51
- **Current Behavior:** Dialog closes before async operation completes. No loading state.
- **Proposed Fix:** Make `onConfirm` awaitable, add loading state, close after completion.
- **Status:** `[ ] NOT STARTED`

## FIX-006: Notification Polling Every 30s Regardless of Tab Visibility
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (M9)
- **File(s):** `src/components/layout/Header.tsx` line 50
- **Current Behavior:** Polls every 30s even in background tab.
- **Proposed Fix:** Use `document.visibilityState` to pause when hidden.
- **Status:** `[ ] NOT STARTED`

## FIX-007: Brand Detail Page 920-Line God Component
- **Severity:** HIGH
- **Source:** Phase 1 Frontend (H4), Phase 8 UX (C1, H1)
- **File(s):** `src/app/brands/[id]/page.tsx` (920 lines, 30+ state variables)
- **Current Behavior:** God component with massive prop drilling (ProductsTab: 26 props, OverviewTab: 17 props).
- **Proposed Fix:** Extract state into a custom hook or Zustand store. Move products/channels/logos into their own state-managing components.
- **Status:** `[ ] NOT STARTED`

## FIX-008: Zustand Installed But Unused
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (package.json), Phase 8 UX (H1)
- **File(s):** `frontend/package.json`
- **Current Behavior:** `zustand@5.0.3` in dependencies but never imported. All state via `useState` with heavy prop drilling.
- **Proposed Fix:** Either use Zustand for shared brand state (eliminating prop drilling) or remove the dependency.
- **Status:** `[ ] NOT STARTED`

## FIX-009: BrandSwitcher CustomEvent Pattern
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (M8), Phase 8 UX (H2)
- **File(s):** `src/components/layout/BrandSwitcher.tsx` line 38; `src/app/content/page.tsx` line 84
- **Current Behavior:** `CustomEvent` on `window` for cross-component communication. Only consumed by ContentStudioPage — other pages ignore it.
- **Proposed Fix:** Use Zustand store or React Context for selected brand state.
- **Status:** `[ ] NOT STARTED`

## FIX-010: Agents Config Lacks Production Secret Validation
- **Severity:** MEDIUM
- **Source:** Phase 9 Infrastructure (I9-12)
- **File(s):** `agents/shared/config.py`
- **Current Behavior:** Unlike backend, agents service does not validate critical secrets are non-default in production.
- **Proposed Fix:** Add startup validation matching `backend/app/config.py` lines 128-159.
- **Status:** `[ ] NOT STARTED`

## FIX-011: Backend Has No /metrics Endpoint
- **Severity:** MEDIUM
- **Source:** Phase 9 Infrastructure (I9-15)
- **File(s):** `backend/app/main.py`
- **Current Behavior:** Prometheus scrapes `backend:8000/metrics` but endpoint doesn't exist. 404 on every scrape.
- **Proposed Fix:** Install `prometheus-fastapi-instrumentator` and mount on app.
- **Status:** `[ ] NOT STARTED`

## FIX-012: No Alerting Rules Defined
- **Severity:** MEDIUM
- **Source:** Phase 9 Infrastructure (I9-16)
- **File(s):** `observability/prometheus/prometheus.yml`
- **Current Behavior:** No alerting rules, no alertmanager config. No automated alerts for critical conditions.
- **Proposed Fix:** Create `observability/prometheus/rules/alerts.yml` with rules for service down, high error rate, high latency, disk/memory utilization.
- **Status:** `[ ] NOT STARTED`

## FIX-013: No Log Shipping from App Containers to Loki
- **Severity:** MEDIUM
- **Source:** Phase 9 Infrastructure (I9-21)
- **File(s):** All application services
- **Current Behavior:** Loki receives no logs. Pipeline exists but is not wired to application output.
- **Proposed Fix:** Add Promtail container, or configure OTLP log sending, or use Docker logging driver.
- **Status:** `[ ] NOT STARTED`

## FIX-014: No Structured (JSON) Logging
- **Severity:** MEDIUM
- **Source:** Phase 9 Infrastructure (I9-23), Phase 10 Code Quality
- **File(s):** All Python services
- **Current Behavior:** Plain text logging. No correlation IDs. Difficult to parse in Loki.
- **Proposed Fix:** Adopt `structlog` with JSON output. Bind contextual fields (request_id, trace_id, brand_id).
- **Status:** `[ ] NOT STARTED`

## FIX-015: Engagement Puller Doesn't Handle YouTube/TikTok/X
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M9)
- **File(s):** `backend/app/scheduler/engagement_puller.py` lines 88-100
- **Current Behavior:** Only handles Instagram, Facebook, LinkedIn. Other channels silently skipped.
- **Proposed Fix:** Add engagement pulling for remaining platforms or log informative message.
- **Status:** `[ ] NOT STARTED`

## FIX-016: _check_minio Accesses _client Without Null Check
- **Severity:** MEDIUM
- **Source:** Phase 1 Backend (M1, M2)
- **File(s):** `backend/app/api/v1/system.py` lines 72, 283
- **Current Behavior:** If MinIO client not initialized, raises `AttributeError` instead of returning "error".
- **Proposed Fix:** Use `minio_service.get_client().list_buckets()` which handles lazy initialization.
- **Status:** `[ ] NOT STARTED`

## FIX-017: Seed Script Schema Mismatch
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (M-18)
- **File(s):** `scripts/seed-dev.py` lines 27-91
- **Current Behavior:** Seed script field names don't match actual database schema/API endpoints. Will fail with 400 errors.
- **Proposed Fix:** Update seed script to match actual schema.
- **Status:** `[ ] NOT STARTED`

## FIX-018: Loki Retention Period Not Configured
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (M-3)
- **File(s):** `observability/loki/loki-config.yaml`
- **Current Behavior:** Retention enabled but no `retention_period` specified. Logs never deleted; disk grows unbounded.
- **Proposed Fix:** Add `retention_period: 720h` (30 days) to `limits_config`.
- **Status:** `[ ] NOT STARTED`

## FIX-019: depends_on Uses service_started Instead of service_healthy
- **Severity:** MEDIUM
- **Source:** Phase 1 Infra (M-9, M-10, M-11)
- **File(s):** `docker-compose.yml` lines 260-271 (agents), 201-213 (backend), 311 (notifications)
- **Current Behavior:** Agents/backend/notifications may start before dependencies are ready.
- **Proposed Fix:** Change to `condition: service_healthy` for all dependencies with healthchecks.
- **Status:** `[ ] NOT STARTED`

## FIX-020: validate_llm_output Only Checks First List Item
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M1)
- **File(s):** `agents/shared/llm.py` lines 125-141
- **Current Behavior:** When `expect_list=True`, validation only checks `data[0]`. Subsequent items could be missing required fields.
- **Proposed Fix:** Check all items in the list.
- **Status:** `[ ] NOT STARTED`

## FIX-021: No Social API Rate Limiting
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M6)
- **File(s):** `agents/shared/tools/social.py`
- **Current Behavior:** No rate limiting or backoff on Instagram/Facebook/LinkedIn API calls.
- **Proposed Fix:** Add rate limiting and retry-with-backoff for 429 responses.
- **Status:** `[ ] NOT STARTED`

## FIX-022: generate_mockups Always Generates All 4 Platforms
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M9)
- **File(s):** `agents/workflows/content/nodes.py` lines 838-856
- **Current Behavior:** Generates mockups for all platforms regardless of which channels are enabled.
- **Proposed Fix:** Read enabled channels from brand config. Only generate for those platforms.
- **Status:** `[ ] NOT STARTED`

## FIX-023: Hardcoded Username in Image Mockup
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M18)
- **File(s):** `agents/shared/image_processing.py` line 253
- **Current Behavior:** Default `username="healthspan.mu"` hardcoded. All brands get this username unless overridden.
- **Proposed Fix:** Pass brand-specific username from `brand_guidelines.channels.instagram.handle`.
- **Status:** `[ ] NOT STARTED`

## FIX-024: Sidebar Has No Mobile Breakpoint
- **Severity:** HIGH
- **Source:** Phase 8 UX (C2)
- **File(s):** `src/components/layout/Sidebar.tsx`
- **Current Behavior:** Sidebar takes fixed 64px/256px regardless of screen width. No hamburger menu, no mobile navigation.
- **Proposed Fix:** Add mobile breakpoint to hide sidebar. Add hamburger/sheet-style mobile menu.
- **Status:** `[ ] NOT STARTED`

## FIX-025: CalendarView Unusable on Mobile
- **Severity:** MEDIUM
- **Source:** Phase 8 UX (C3)
- **File(s):** `src/components/content/CalendarView.tsx`
- **Current Behavior:** 7-column grid never changes. On mobile, each cell is ~53px wide, content unreadable.
- **Proposed Fix:** Use responsive layout (list view on mobile, grid on desktop).
- **Status:** `[ ] NOT STARTED`

---

# PHASE G: LOW-SEVERITY & POLISH

## LOW-001: Dead Imports in gemini_service.py
- **Severity:** LOW
- **Source:** Phase 1 Backend (L1, L2)
- **File(s):** `backend/app/services/gemini_service.py` lines 9, 11
- **Current Behavior:** `import base64` and `import re` are imported but never used.
- **Proposed Fix:** Remove unused imports.
- **Status:** `[ ] NOT STARTED`

## LOW-002: ROLE_HIERARCHY Is Redundant Copy of ROLES
- **Severity:** LOW
- **Source:** Phase 1 Backend (L3)
- **File(s):** `backend/app/auth/permissions.py` lines 6-13
- **Current Behavior:** `ROLE_HIERARCHY = {role: level for role, level in ROLES.items()}` is identical to `ROLES`.
- **Proposed Fix:** Remove `ROLE_HIERARCHY` or alias it.
- **Status:** `[ ] NOT STARTED`

## LOW-003: Unused deliver_policy Parameter
- **Severity:** LOW
- **Source:** Phase 1 Backend (L4)
- **File(s):** `backend/app/services/nats_service.py` line 76
- **Current Behavior:** `deliver_policy` accepted but never used.
- **Proposed Fix:** Pass it to `pull_subscribe()` or remove it.
- **Status:** `[ ] NOT STARTED`

## LOW-004: No Logging When Image Download Fails
- **Severity:** LOW
- **Source:** Phase 1 Backend (L5)
- **File(s):** `backend/app/services/gemini_service.py` line 148
- **Current Behavior:** `except Exception: continue` silently swallows errors.
- **Proposed Fix:** Add `logger.debug(...)`.
- **Status:** `[ ] NOT STARTED`

## LOW-005: content_service.list_content Accepts **kwargs Silently
- **Severity:** LOW
- **Source:** Phase 1 Backend (L8)
- **File(s):** `backend/app/services/content_service.py` line 22
- **Current Behavior:** Misspelled keyword arguments silently ignored.
- **Proposed Fix:** Remove `**kwargs`.
- **Status:** `[ ] NOT STARTED`

## LOW-006: No Timeout on NATS Connection
- **Severity:** LOW
- **Source:** Phase 1 Backend (L9)
- **File(s):** `backend/app/services/nats_service.py` line 31
- **Current Behavior:** No connection timeout. Could hang indefinitely.
- **Proposed Fix:** Add `connect_timeout=5`.
- **Status:** `[ ] NOT STARTED`

## LOW-007: Inconsistent UUID-to-String in Raw SQL
- **Severity:** LOW
- **Source:** Phase 1 Backend (L7)
- **File(s):** `backend/app/api/v1/brands.py` line 111; `backend/app/api/v1/analytics.py` line 80
- **Current Behavior:** Some raw SQL passes UUIDs as `str(brand_id)`.
- **Proposed Fix:** Use UUID objects consistently.
- **Status:** `[ ] NOT STARTED`

## LOW-008: Alembic env.py Hardcodes Fallback Credentials
- **Severity:** LOW
- **Source:** Phase 1 Backend (L12)
- **File(s):** `backend/alembic/env.py` lines 33-36
- **Current Behavior:** Fallback DATABASE_URL uses `markai:markai`.
- **Proposed Fix:** Raise error if `DATABASE_URL` not set.
- **Status:** `[ ] NOT STARTED`

## LOW-009: Duplicate Calendar Endpoints
- **Severity:** LOW
- **Source:** Phase 1 Backend (M12, L13), Phase 5 Performance (X1, X2), Phase 7 API (H4)
- **File(s):** `backend/app/api/v1/content.py` lines 19-79 vs `backend/app/api/v1/calendar.py`
- **Current Behavior:** Two near-identical upcoming calendar endpoints.
- **Proposed Fix:** Deprecate/remove the duplicate in content.py.
- **Status:** `[ ] NOT STARTED`

## LOW-010: require_role Decorator Never Used
- **Severity:** LOW
- **Source:** Phase 1 Backend (M13), Phase 10 Code Quality
- **File(s):** `backend/app/auth/permissions.py` lines 23-48
- **Current Behavior:** Dead code.
- **Proposed Fix:** Remove or standardize usage.
- **Status:** `[ ] NOT STARTED`

## LOW-011: Worker Imports Inside Function Bodies
- **Severity:** LOW
- **Source:** Phase 1 Agents (L7)
- **File(s):** `agents/worker.py` lines 112, 167, 225, 275
- **Current Behavior:** Database imports inside function bodies.
- **Proposed Fix:** Move to top of file.
- **Status:** `[ ] NOT STARTED`

## LOW-012: PNG quality Parameter Ignored
- **Severity:** LOW
- **Source:** Phase 1 Agents (L12)
- **File(s):** `agents/shared/image_processing.py` lines 203, 279
- **Current Behavior:** `quality=95` on PNG saves — PNG doesn't support quality param. Pillow ignores it.
- **Proposed Fix:** Remove `quality=95` or change to `compress_level=6`.
- **Status:** `[ ] NOT STARTED`

## LOW-013: No README.md
- **Severity:** HIGH
- **Source:** Phase 11 Documentation
- **File(s):** Root directory
- **Current Behavior:** No README exists. Zero onboarding orientation.
- **Proposed Fix:** Create README with project overview, quickstart, architecture links.
- **Status:** `[ ] NOT STARTED`

## LOW-014: No CONTRIBUTING.md
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** Root directory
- **Current Behavior:** No contributing guide, PR template, or issue template.
- **Proposed Fix:** Create CONTRIBUTING.md with branching strategy, PR process, coding standards.
- **Status:** `[ ] NOT STARTED`

## LOW-015: No Makefile or Task Runner
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** Root directory
- **Current Behavior:** No `make dev`, `make test`, `make lint`, etc.
- **Proposed Fix:** Add Makefile with common targets.
- **Status:** `[ ] NOT STARTED`

## LOW-016: No Pre-commit Hooks
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** Root directory
- **Current Behavior:** No automated lint/format checks before commit.
- **Proposed Fix:** Add pre-commit config with ruff + eslint hooks.
- **Status:** `[ ] NOT STARTED`

## LOW-017: No .editorconfig
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** Root directory
- **Current Behavior:** No shared editor settings for indentation, line endings, etc.
- **Proposed Fix:** Add `.editorconfig`.
- **Status:** `[ ] NOT STARTED`

## LOW-018: Backend Docstring Coverage Very Low (~5%)
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** `backend/app/` (81 files)
- **Current Behavior:** Almost no module-level docstrings in backend route/service files.
- **Proposed Fix:** Add module-level and function-level docstrings to complex business logic.
- **Status:** `[ ] NOT STARTED`

## LOW-019: Frontend Hot Reload Broken in Docker
- **Severity:** LOW
- **Source:** Phase 11 Documentation
- **File(s):** `docker-compose.override.yml`
- **Current Behavior:** Port 3000 exposed but no volume mount for frontend source. Changes require container rebuild.
- **Proposed Fix:** Add `./frontend/src:/app/src` volume mount and `npm run dev` command.
- **Status:** `[ ] NOT STARTED`

## LOW-020: Ruff Configured But Has No Rules
- **Severity:** LOW
- **Source:** Phase 10 Code Quality
- **File(s):** All `pyproject.toml` files
- **Current Behavior:** Ruff listed as dev dependency but no `[tool.ruff]` config. Essentially a no-op.
- **Proposed Fix:** Add `[tool.ruff]` section with line-length, select rules, isort.
- **Status:** `[ ] NOT STARTED`

## LOW-021: Inconsistent API Response Formats
- **Severity:** LOW
- **Source:** Phase 7 API (M1), Phase 10 Code Quality
- **File(s):** Multiple API endpoints
- **Current Behavior:** Mixed Pydantic models, raw dicts, and different pagination patterns.
- **Proposed Fix:** Standardize on response envelope `{data, meta, errors}`.
- **Status:** `[ ] NOT STARTED`

## LOW-022: Worker _handle_message God Function
- **Severity:** MEDIUM
- **Source:** Phase 1 Agents (M12), Phase 10 Code Quality
- **File(s):** `agents/worker.py` lines 80-345 (~265 lines)
- **Current Behavior:** Single function handles message parsing, dispatch, lifecycle, chaining, timeouts, errors.
- **Proposed Fix:** Extract into smaller functions: `_dispatch_workflow()`, `_handle_chain()`, `_handle_sequential_content()`.
- **Status:** `[ ] NOT STARTED`

## LOW-023: Accessibility Issues — Dialogs/ARIA/Focus
- **Severity:** MEDIUM
- **Source:** Phase 1 Frontend (H11), Phase 8 UX (H4, H5, M1-M6)
- **File(s):** `src/components/content/CalendarView.tsx`; `src/components/content/AssetPreview.tsx`; `src/components/content/PlatformMockups.tsx`; various
- **Current Behavior:** Calendar overlay lacks focus trap/Escape/dialog role. Multiple dialogs missing `DialogTitle`. Sidebar collapse button missing `aria-label`/`aria-expanded`. Product checkboxes lack labels.
- **Proposed Fix:** Use Radix Dialog for overlays. Add ARIA attributes throughout. Add visually hidden DialogTitle elements.
- **Status:** `[ ] NOT STARTED`

## LOW-024: Promptfoo Config References Non-Existent Files
- **Severity:** LOW
- **Source:** Phase 1 Infra (L-2)
- **File(s):** `eval/promptfooconfig.yaml` lines 11-12
- **Current Behavior:** References `prompts/content_generation.txt` and `prompts/research_summary.txt` but no `eval/prompts/` directory exists.
- **Proposed Fix:** Create the referenced files or update paths.
- **Status:** `[ ] NOT STARTED`

## LOW-025: Notifications Service Uses Different Redis Package
- **Severity:** LOW
- **Source:** Phase 1 Infra (H-10)
- **File(s):** `notifications/pyproject.toml` (uses `valkey`), `backend/pyproject.toml` (uses `redis`)
- **Current Behavior:** Two different client libraries for the same Valkey server.
- **Proposed Fix:** Standardize on one package across all services.
- **Status:** `[ ] NOT STARTED`

---

*End of Master Remediation Plan — 97 findings across 7 phases*
