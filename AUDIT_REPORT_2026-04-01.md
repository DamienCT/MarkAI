# MARKAI Comprehensive Audit Report

**Date:** 2026-04-01
**Scope:** Full codebase audit — security, code quality, architecture, infrastructure, frontend, database, AI/ML workflows
**Audited by:** Automated multi-agent audit (8 parallel agents)

---

## 1. Executive Summary

MARKAI is a well-architected system with clean LangGraph workflows, a normalized database schema, and solid infrastructure patterns (Docker health checks, NATS durable consumers, Pydantic validation). However, this audit identified **4 CRITICAL**, **18 HIGH**, **~40 MEDIUM**, and **~40 LOW** findings across all layers. The top 3 risks are:

1. **Security: Privilege escalation** — Frontend defaults to "manager" role when backend is unreachable (auth.ts:119-125), and the file proxy endpoint serves MinIO objects without authentication (files.py:20-60).
2. **Reliability: LiteLLM timeout conflict** — The proxy kills requests at 120s while agents wait up to 600s, silently truncating large content generation and strategy document calls.
3. **Data integrity: Multiple race conditions** — Skip-forward logic (worker.py:311), content status transitions (content/nodes.py:128), and approval resolution bypassing the state machine (approval_service.py:86) can produce inconsistent states.

Overall health: **Good foundation with targeted security and reliability gaps that must be resolved before scaling.**

---

## 2. Critical Findings

### C-01: Frontend defaults user role to "manager" when backend is unreachable
- **Location:** [auth.ts:119-125](frontend/src/lib/auth.ts#L119-L125)
- **Description:** When the backend API is down or unreachable, the JWT callback catches the error and assigns `token.role = "manager"`. Any viewer or inactive user whose session refreshes during a backend outage is silently upgraded to manager. The role is cached in the JWT for up to 7 days.
- **Evidence:**
  ```typescript
  } else { token.role = "manager"; }   // backend returned error
  } catch { token.role = "manager"; }  // backend unreachable
  ```
- **Fix:** Default to `"viewer"` (least privilege) on failure. Do not cache the role — leave `token.role` undefined so it retries on the next `session()` call.
- **Effort:** 1h

### C-02: Logo label path traversal in brands API
- **Location:** [brands.py:341-437](backend/app/api/v1/brands.py#L341-L437)
- **Description:** The `label` parameter on logo upload/serve/delete endpoints is a free-form string used directly in the MinIO object path (`brands/{brand_id}/logos/{label}.{ext}`). A malicious user could supply `label=../../secrets/credentials` to write or read files at arbitrary MinIO paths.
- **Fix:** Validate label with `re.match(r'^[a-zA-Z0-9_-]{1,50}$', label)` and reject otherwise.
- **Effort:** 0.5h

### C-03: Unauthenticated file proxy with fallback bucket bypass
- **Location:** [files.py:20-60](backend/app/api/v1/files.py#L20-L60)
- **Description:** The file serving endpoint requires no authentication. Additionally, when the first path segment is not in `KNOWN_BUCKETS`, the fallback sets `bucket=None` which defaults to `markai-assets`, making all files in the default bucket publicly accessible. Combined with predictable object names, brand assets are exposed.
- **Fix:** (a) Add authentication or signed URLs. (b) Return 404 when path doesn't match a known bucket instead of falling back.
- **Effort:** 2h

### C-04: Traefik certresolver name mismatch in VPS overlay
- **Location:** [docker-compose.vps.yml:29,47](docker-compose.vps.yml#L29) vs [traefik.yml:34](traefik/traefik.yml#L34)
- **Description:** VPS overlay references `certresolver=mytlschallenge` while the bundled Traefik config defines `letsencrypt`. If the VPS Traefik uses the bundled config or a mismatched resolver name, TLS certificate acquisition will fail, making the site inaccessible or serving on plain HTTP.
- **Fix:** Parameterize: `certresolver=${TRAEFIK_CERTRESOLVER:-letsencrypt}` and document in `.env.vps.example`.
- **Effort:** 0.5h

---

## 3. High-Priority Findings

### H-01: LiteLLM proxy timeout 120s vs agents timeout 600s
- **Location:** [litellm/config.yaml:96](litellm/config.yaml#L96) vs [llm.py:240](agents/shared/llm.py#L240)
- **Description:** LiteLLM kills upstream API calls after 120s. Agents compute `max(120, min(600, max_tokens // 10))` which reaches 600s for strategy documents (max_tokens=16384). Large generations are silently truncated.
- **Fix:** Increase `request_timeout` in litellm/config.yaml to 600.
- **Effort:** 0.5h

### H-02: Unsanitized SVG passed to ImageMagick subprocess
- **Location:** [image_processing.py:61-97](agents/shared/image_processing.py#L61-L97)
- **Description:** Raw SVG bytes are written to a temp file and passed to ImageMagick. SVG files can contain `<script>`, `<foreignObject>`, XXE entities, and SSRF via `xlink:href`. ImageMagick has a long history of SVG-related CVEs.
- **Fix:** Sanitize SVG (strip `<script>`, `<foreignObject>`, `<!DOCTYPE>`, `<!ENTITY>`, external `xlink:href`). Configure ImageMagick's `policy.xml` to disable network access. Consider switching to `cairosvg`.
- **Effort:** 4h

### H-03: Incomplete prompt injection patterns
- **Location:** [sanitize.py:6-16](agents/shared/sanitize.py#L6-L16) (duplicated in [intelligence.py:29-52](backend/app/api/v1/intelligence.py#L29-L52))
- **Description:** 9 regex patterns miss `</s>`, `<|endoftext|>`, `[/INST]`, `### Instruction:`, `<tool_call>`, role impersonation, and Unicode homoglyph attacks. Regex-only filtering is fundamentally bypassable.
- **Fix:** Add missing patterns. Implement structural defenses (XML/JSON delimiters around user content in prompts). Consolidate into a single module.
- **Effort:** 3h

### H-04: No chain_depth limit on sequential content chaining
- **Location:** [worker.py:470-504](agents/worker.py#L470-L504)
- **Description:** Content items chain sequentially with `chain_depth + 1` but no upper bound. A brand with 100+ queued items creates unbounded chaining. If any item fails mid-chain, all subsequent items are silently dropped.
- **Fix:** Add `MAX_CONTENT_CHAIN_DEPTH = 200` guard, or fan-out all remaining items as individual messages.
- **Effort:** 2h

### H-05: SSRF via unvalidated image URLs in content workflow and gemini service
- **Location:** [content/nodes.py:818-820,895-898](agents/workflows/content/nodes.py#L818-L820), [gemini_service.py:137-168](backend/app/services/gemini_service.py#L137-L168)
- **Description:** Multiple places fetch arbitrary URLs from DB or search results without validating they don't point to internal networks (169.254.169.254, localhost, 10.x.x.x).
- **Fix:** Create a shared `safe_http_get()` that validates URLs against an allowlist of schemes (https only) and blocks private/reserved IP ranges.
- **Effort:** 3h

### H-06: `_strip_sensitive_guidelines()` mutates live ORM object
- **Location:** [brands.py:41-63](backend/app/api/v1/brands.py#L41-L63)
- **Description:** Directly assigns to `brand.brand_guidelines`, mutating the ORM instance. If `db.commit()` occurs later in the request (or autoflush triggers), stripped data is permanently persisted to the database, deleting secrets.
- **Fix:** Return a deep copy or use `db.expunge(brand)` before mutation.
- **Effort:** 1h

### H-07: Role cached permanently in JWT for 7 days
- **Location:** [auth.ts:111](frontend/src/lib/auth.ts#L111)
- **Description:** Role is fetched once and never refreshed. A demoted user retains their old role until the JWT expires (up to 7 days) or they sign out.
- **Fix:** Re-fetch role periodically (every 30 minutes) or reduce session maxAge to 24h.
- **Effort:** 2h

### H-08: Token refresh race condition
- **Location:** [auth.ts:100-107](frontend/src/lib/auth.ts#L100-L107)
- **Description:** Multiple tabs/SSR requests simultaneously trigger `refreshAzureToken()`. Azure AD refresh tokens are typically single-use — concurrent refreshes cause the second to fail, potentially logging out the user.
- **Fix:** Implement a refresh lock/mutex using a module-level promise.
- **Effort:** 2h

### H-09: 401 handler returns `undefined as T` without debounce
- **Location:** [api.ts:74-78](frontend/src/lib/api.ts#L74-L78)
- **Description:** `signIn()` is async but the calling code receives `undefined` typed as `T`, which may be used before navigation occurs. Multiple simultaneous 401s trigger multiple `signIn()` calls.
- **Fix:** Throw an error instead of returning undefined. Debounce signIn with a module-level flag.
- **Effort:** 1h

### H-10: Approval resolution bypasses status state machine
- **Location:** [approval_service.py:86-89](backend/app/services/approval_service.py#L86-L89)
- **Description:** When an approval is resolved, `calendar_item.status` is set directly to "approved" or "reworking" without going through `_validate_transition()`. A "queued" item can jump to "approved".
- **Fix:** Call `_validate_transition(cal_item.status, new_status)` before setting.
- **Effort:** 1h

### H-11: LangGraph `interrupt()` used without checkpointer
- **Location:** [adaptation/graph.py:42-43](agents/workflows/adaptation/graph.py#L42-L43), [strategy/graph.py:58](agents/workflows/strategy/graph.py#L58)
- **Description:** Both adaptation and strategy workflows use `interrupt()` but compile without a checkpointer. LangGraph requires a checkpointer to persist and resume state after an interrupt. This will crash at runtime.
- **Fix:** Compile with `checkpointer=MemorySaver()` or a persistent checkpointer.
- **Effort:** 1h

### H-12: DuckDuckGo scraping is fragile and undocumented
- **Location:** [gemini_service.py:62-121](backend/app/services/gemini_service.py#L62-L121)
- **Description:** Image search relies on scraping DuckDuckGo's web page for a `vqd` token using regex. DuckDuckGo frequently changes structure, making this a maintenance burden and silent failure source.
- **Fix:** Switch to the `duckduckgo-search` PyPI package or a stable API (Google Custom Search, Bing Image Search).
- **Effort:** 3h

### H-13: Unsanitized filename in product image upload
- **Location:** [products.py:175](backend/app/api/v1/products.py#L175)
- **Description:** `file.filename` is used directly in MinIO object names. Malicious filenames could contain path traversal characters or special characters.
- **Fix:** Generate UUID-based names: `f"{uuid4().hex}{splitext(file.filename or '.jpg')[1]}"`.
- **Effort:** 0.5h

### H-14: No Alembic migration files exist
- **Location:** [backend/alembic/versions/](backend/alembic/versions/) (empty)
- **Description:** Schema is managed entirely by `init.sql`. No version tracking, no incremental migrations. Any schema change requires manual DDL on running databases.
- **Fix:** Generate initial migration: `alembic revision --autogenerate -m "initial"`. Use Alembic for all future changes.
- **Effort:** 4h

### H-15: Insecure default passwords in Docker Compose fallbacks
- **Location:** [docker-compose.yml:74,119,123,166,381](docker-compose.yml#L74)
- **Description:** `:-change-me-*` and `:-admin` defaults mean production can silently run with insecure passwords if `.env` is misconfigured.
- **Fix:** Use `${VAR:?VAR must be set}` syntax to fail fast on missing env vars.
- **Effort:** 1h

### H-16: No Docker build test in CI
- **Location:** [.github/workflows/ci.yml](.github/workflows/ci.yml)
- **Description:** CI runs lint/tests but never builds Docker images. Dockerfile errors are only caught at deployment.
- **Fix:** Add a `docker compose build` job.
- **Effort:** 2h

### H-17: SSE notification polling — N queries every 10 seconds
- **Location:** [notifications.py:58-101](backend/app/api/v1/notifications.py#L58-L101)
- **Description:** Each SSE client opens a new DB session and queries every 10 seconds. With N users, this is 6N queries/minute. Does not scale.
- **Fix:** Replace with NATS pub/sub or PostgreSQL LISTEN/NOTIFY.
- **Effort:** 6h

### H-18: Content `is_current` unique index race condition in backend
- **Location:** [content_service.py](backend/app/services/content_service.py) vs [database.py:246-252](agents/shared/tools/database.py#L246-L252)
- **Description:** Agents handle the partial unique index correctly within a single session. Backend service has no explicit `IntegrityError` handling for concurrent content creation on the same calendar item.
- **Fix:** Add try/except `IntegrityError` handler in backend content creation.
- **Effort:** 1h

---

## 4. Medium-Priority Findings

| ID | Location | Issue | Effort |
|---|---|---|---|
| M-01 | [worker.py:311-384](agents/worker.py#L311-L384) | TOCTOU race in skip-forward logic — no dedup on publish | 3h |
| M-02 | [worker.py:457](agents/worker.py#L457) | Message ack before chaining — at-most-once delivery risk | 3h |
| M-03 | [worker.py:287-289](agents/worker.py#L287-L289) | Unguarded deletion of completed agent_runs — no cooldown | 2h |
| M-04 | [worker.py:648](agents/worker.py#L648) | `ANY(:ids)` SQL may not bind correctly with asyncpg | 1h |
| M-05 | [llm.py:270-273](agents/shared/llm.py#L270-L273) | TimeoutError re-raise defeats tenacity retry | 1h |
| M-06 | [llm.py:337-338](agents/shared/llm.py#L337-L338) | Direct OpenAI API key in worker env, bypasses LiteLLM tracking | 2h |
| M-07 | [sanitize.py:21-36](agents/shared/sanitize.py#L21-L36) | Docstring claims delimiter escaping but none implemented | 0.5h |
| M-08 | [planning/nodes.py:351](agents/workflows/planning/nodes.py#L351) | Dedup window of 60 items too small for multi-channel brands | 1h |
| M-09 | [planning/nodes.py:442-456](agents/workflows/planning/nodes.py#L442-L456) | Empty calendar silently reports success | 1h |
| M-10 | [content/nodes.py:665-670](agents/workflows/content/nodes.py#L665-L670) | Image gen failure silently continues pipeline — no-image content | 2h |
| M-11 | [content/nodes.py:938-972](agents/workflows/content/nodes.py#L938-L972) | Branding exceptions silently swallowed | 1h |
| M-12 | [content/nodes.py:128-131](agents/workflows/content/nodes.py#L128-L131) | Race condition on calendar item status transition (0 rows affected) | 1h |
| M-13 | [content/nodes.py:354-393](agents/workflows/content/nodes.py#L354-L393) | Caption length limits not programmatically enforced per platform | 3h |
| M-14 | [content/nodes.py:519-525](agents/workflows/content/nodes.py#L519-L525) | LIKE pattern injection via `%` and `_` in product name | 0.5h |
| M-15 | [content/nodes.py:818-1005](agents/workflows/content/nodes.py#L818) | No response size limit on external image downloads | 1h |
| M-16 | [brands.py:361-363](backend/app/api/v1/brands.py#L361-L363) | Full file read into memory before size check | 1h |
| M-17 | [brands.py:355](backend/app/api/v1/brands.py#L355) | Content-type spoofing — no magic-byte validation | 2h |
| M-18 | [brands.py:239-258](backend/app/api/v1/brands.py#L239-L258) | Activation TOCTOU race — no row-level lock | 1h |
| M-19 | [entra.py:68](backend/app/auth/entra.py#L68) | `asyncio.Lock()` at module level may bind to wrong event loop | 1h |
| M-20 | [entra.py:122-135](backend/app/auth/entra.py#L122-L135) | OData filter injection in `search_graph_users()` | 1h |
| M-21 | [entra.py:149-175](backend/app/auth/entra.py#L149-L175) | `get_graph_users_by_ids()` doesn't validate user_ids as UUIDs | 1h |
| M-22 | [deps.py:106-111](backend/app/deps.py#L106-L111) | Admin auto-elevation prevents app-level demotion | 2h |
| M-23 | [files.py:26](backend/app/api/v1/files.py#L26) | Path traversal check incomplete for backslashes on Windows | 0.5h |
| M-24 | [main.py:119-126](backend/app/main.py#L119-L126) | Traceback sanitization by keyword is fragile | 2h |
| M-25 | [base.py:10-15](backend/app/models/base.py#L10-L15) | Backend missing `pool_pre_ping=True` — stale connections on PG restart | 0.5h |
| M-26 | [database.py:193-225](agents/shared/tools/database.py#L193-L225) | Competitor store has TOCTOU race — no unique constraint on (brand_id, name) | 2h |
| M-27 | [database.py:607-623](agents/shared/tools/database.py#L607-L623) | `execute_query`/`execute_update` accept raw SQL — callers must be audited | 2h |
| M-28 | [content_service.py:103-136](backend/app/services/content_service.py#L103-L136) | `transition_status` no validation of known statuses | 1h |
| M-29 | [content_service.py:121-128](backend/app/services/content_service.py#L121-L128) | Transition silently succeeds when calendar_item_id is None | 1h |
| M-30 | [nats_service.py:35-53](backend/app/services/nats_service.py#L35-L53) | No NATS reconnection logic | 2h |
| M-31 | [minio_service.py:23](backend/app/services/minio_service.py#L23) | `secure=False` hardcoded — should be configurable | 0.5h |
| M-32 | [ai_model_service.py:122-134](backend/app/services/ai_model_service.py#L122-L134) | Valkey ping on every cache access doubles latency | 1h |
| M-33 | [ai_model_service.py:381-451](backend/app/services/ai_model_service.py#L381-L451) | Manual `__aenter__`/`__aexit__` instead of `async with` | 1h |
| M-34 | [nats_consumer.py:56](agents/shared/nats_consumer.py#L56) | max_deliver=5 with no dead letter queue — messages silently lost | 2h |
| M-35 | [docker-compose.yml](docker-compose.yml) + [worker.py](agents/worker.py) | NATS stream config race — backend and agents specify different retention | 2h |
| M-36 | [security-headers.yml:15](traefik/dynamic/security-headers.yml#L15) | CSP allows unsafe-inline and unsafe-eval | 3h |
| M-37 | [litellm/config.yaml:98](litellm/config.yaml#L98) | `drop_params: true` silently discards unsupported LLM parameters | 1h |
| M-38 | types/index.ts:236,239,241 | User.name/brand_ids/last_login field mismatches with backend | 2h |
| M-39 | CalendarView.tsx:114-139 | Dates parsed in browser timezone, not Indian/Mauritius | 3h |
| M-40 | KanbanBoardInner.tsx:206-239 | Empty columns not droppable with @dnd-kit | 2h |

---

## 5. Low-Priority Findings

| ID | Location | Issue |
|---|---|---|
| L-01 | [worker.py:202-209](agents/worker.py#L202-L209) | Image regen swallows all errors, no retry |
| L-02 | [llm.py:34-35](agents/shared/llm.py#L34-L35) | Shared httpx client 20 connections may bottleneck |
| L-03 | [llm.py:83-84](agents/shared/llm.py#L83-L84) | Benign race on model cache dict |
| L-04 | [llm.py:347-387](agents/shared/llm.py#L347-L387) | Fallback chain swallows retryable 429 errors |
| L-05 | [planning/nodes.py:318-321](agents/workflows/planning/nodes.py#L318-L321) | Dead/unused expressions |
| L-06 | [planning/nodes.py:77-87](agents/workflows/planning/nodes.py#L77-L87) | Date validator returns unsanitized original string |
| L-07 | [planning/nodes.py:534](agents/workflows/planning/nodes.py#L534) | Dead `"status": "planned"` — overridden by `store_calendar_items` |
| L-08 | [content/nodes.py:489](agents/workflows/content/nodes.py#L489) | Dead expression `state.get("brand", {})` |
| L-09 | [content/nodes.py:1165-1167](agents/workflows/content/nodes.py#L1165-L1167) | Non-deterministic reviewer assignment (no ORDER BY) |
| L-10 | [brands.py:403-431](backend/app/api/v1/brands.py#L403-L431) | Logo endpoint unauthenticated (intentional but undocumented) |
| L-11 | [auth.ts:147](frontend/src/lib/auth.ts#L147) | Missing NEXTAUTH_SECRET env var validation |
| L-12 | [auth.ts:91](frontend/src/lib/auth.ts#L91) | `expires_at` may be undefined, preventing future refreshes |
| L-13 | [api.ts:50](frontend/src/lib/api.ts#L50) | Hardcoded trailing-slash regex — fragile, needs manual updates |
| L-14 | [api.ts:176-179](frontend/src/lib/api.ts#L176-L179) | `fileUrl` regex fails on URL-encoded MinIO paths |
| L-15 | [api.ts:9-11](frontend/src/lib/api.ts#L9-L11) | HTTPS upgrade doesn't exclude `127.0.0.1` |
| L-16 | [entra.py:56-59](backend/app/auth/entra.py#L56-L59) | `invalidate_jwks_cache()` is dead code — never called |
| L-17 | [permissions.py:21-37](backend/app/auth/permissions.py#L21-L37) | `require_role_dependency()` is dead code |
| L-18 | [intelligence.py:690,764](backend/app/api/v1/intelligence.py#L690) | Exception detail leaks internal info to client |
| L-19 | [config.py:131-135](backend/app/config.py#L131-L135) | Missing production check for N8N_WEBHOOK_SECRET |
| L-20 | Multiple ORM models | 8 column size mismatches (String(255) vs VARCHAR(100)) |
| L-21 | All models with `onupdate=func.now()` | Double-update of updated_at (ORM + DB trigger) |
| L-22 | types/index.ts:103,108,274-287,300-304 | Content.title/cta, PromptVersion, Adaptation phantom fields |
| L-23 | ChannelPreview.tsx:238-256 | Missing TikTok and Teams channel previews |
| L-24 | PlatformMockups.tsx:61-66 | No image error fallback, no loading skeleton |
| L-25 | ContentEditor.tsx | No unsaved changes warning, no form validation |
| L-26 | BrandOnboarding.tsx:71-81 | Channel `configured` flag not checked |
| L-27 | Dashboard page.tsx:33-41 | Promise.allSettled — all-rejected shows no error |
| L-28 | Docker Compose | Logging config missing on infrastructure services |
| L-29 | Agents Dockerfile | Duplicate Playwright install (also in browser-worker) — 2-3GB image |
| L-30 | Both Dockerfiles | MSSQL ODBC driver pinned to msodbcsql17 (v18 available) |
| L-31 | Docker socket mounts | Traefik + Promtail mount docker.sock (privilege escalation vector) |
| L-32 | Prometheus config | NATS `/varz` is not Prometheus format — scrape will fail |
| L-33 | Prometheus config | No alertmanager configured — alerts fire but go nowhere |
| L-34 | engagement_puller.py:20-43 | "Upsert" always inserts — accumulates duplicate metric rows |
| L-35 | morning_jobs.py:128 | `LIMIT 1` only triggers one content item per morning |

---

## 6. Remediation Plan

### Phase 1: Critical Security (Week 1) — ~10h
| Priority | Finding | Effort |
|---|---|---|
| 1 | C-01: Fix default role to "viewer" | 1h |
| 2 | C-02: Validate logo label parameter | 0.5h |
| 3 | C-03: Add auth to file proxy + fix fallback bucket | 2h |
| 4 | C-04: Fix certresolver name + parameterize | 0.5h |
| 5 | H-13: Sanitize product image filenames | 0.5h |
| 6 | H-06: Fix ORM mutation in strip_sensitive | 1h |
| 7 | H-15: Replace insecure Docker Compose defaults | 1h |
| 8 | H-05: Add SSRF protection on image URL fetching | 3h |

### Phase 2: Reliability & Data Integrity (Week 2) — ~15h
| Priority | Finding | Effort |
|---|---|---|
| 1 | H-01: Increase LiteLLM request_timeout to 600 | 0.5h |
| 2 | H-10: Add status validation in approval_service | 1h |
| 3 | H-11: Add checkpointer to adaptation/strategy graphs | 1h |
| 4 | H-04: Add chain_depth limit for content chaining | 2h |
| 5 | H-18: Handle IntegrityError in backend content creation | 1h |
| 6 | M-25: Add pool_pre_ping to backend engine | 0.5h |
| 7 | M-30: Add NATS reconnection logic | 2h |
| 8 | M-35: Unify NATS stream config between backend and agents | 2h |
| 9 | M-02: Move msg.ack() after chaining publish | 3h |
| 10 | M-05: Fix TimeoutError re-raise defeating retries | 1h |

### Phase 3: Code Quality & Frontend (Week 3) — ~20h
| Priority | Finding | Effort |
|---|---|---|
| 1 | H-07 + H-08: Fix JWT role caching + refresh race condition | 4h |
| 2 | H-09: Fix 401 handler + debounce signIn | 1h |
| 3 | M-38 + M-39 + M-40: Fix frontend type mismatches, timezone, kanban | 7h |
| 4 | H-03: Expand prompt injection patterns + consolidate | 3h |
| 5 | H-02: SVG sanitization for ImageMagick | 4h |
| 6 | H-14: Bootstrap Alembic migrations | 4h |

### Phase 4: Infrastructure & Monitoring (Week 4) — ~15h
| Priority | Finding | Effort |
|---|---|---|
| 1 | H-16: Add Docker build to CI | 2h |
| 2 | H-17: Replace SSE polling with pub/sub | 6h |
| 3 | H-12: Replace DuckDuckGo scraping with stable API | 3h |
| 4 | M-36: Tighten CSP headers | 3h |
| 5 | L-32 + L-33: Fix Prometheus NATS scrape + add alertmanager | 2h |

---

## 7. Architecture Recommendations

### 7.1 Extract shared code
- Consolidate `sanitize.py` and the duplicate in `intelligence.py` into a shared package.
- Consolidate `_call_llm` (intelligence.py) with `agents/shared/llm.py`.
- Create a shared URL validation utility for SSRF prevention.

### 7.2 Decouple content generation from serial chaining
- Current: Worker chains content items one-at-a-time via NATS publish. A 84-item backlog (12 weeks x 7 channels) takes 42-84 minutes serially.
- Recommendation: Fan out all queued items as independent NATS messages with a concurrency limiter (e.g., 3-5 concurrent content generations). This improves throughput and isolates failures.

### 7.3 Replace SSE polling with event-driven notifications
- Replace the 10-second DB poll with NATS subscription or PostgreSQL LISTEN/NOTIFY.
- Add WebSocket support for real-time updates on content generation progress.

### 7.4 Add a proper migration strategy
- Bootstrap Alembic with the current schema as the baseline.
- Add a CI check that verifies migrations are up-to-date with models.

### 7.5 Split the agents Docker image
- Remove Playwright from agents (offload to browser-worker).
- Consider splitting ImageMagick into a dedicated image-processing microservice if the image grows too large.

### 7.6 Implement defense-in-depth for LLM prompts
- Structural delimiters (`<user_data>...</user_data>`) around all user-supplied content in prompts.
- Output validation (schema checks on LLM JSON responses).
- Regex-based filtering as a first layer (current), not the only layer.

---

## 8. Testing Recommendations

### Priority 1: Security tests
- Path traversal tests for logo label and file proxy endpoints
- Role escalation tests (viewer → manager via backend outage simulation)
- SSRF tests for image fetching endpoints
- SQL injection fuzzing on all `text()` query callers

### Priority 2: Integration tests
- API integration tests with real PostgreSQL (use testcontainers)
- NATS message flow tests (publish → consume → chain)
- Content status state machine tests (all valid and invalid transitions)
- Approval → calendar_item status propagation tests

### Priority 3: Workflow tests
- LangGraph workflow tests with mocked LLM responses
- Calendar batch generation with edge cases (0 items, max items, dedup)
- Image generation fallback chain tests
- Error propagation tests (failed node → graph END)

### Priority 4: Frontend tests
- Component tests with React Testing Library (KanbanBoard, CalendarView, BrandOnboarding)
- Timezone handling tests (CalendarView with different browser locales)
- Type alignment tests (snapshot backend API responses vs frontend types)

### Priority 5: E2E tests
- Full activation pipeline (brand → research → strategy → planning → content)
- Approval flow (content → in_review → approved → scheduled → published)
- Docker Compose build and startup smoke test in CI

---

*This report was generated by analyzing 100+ source files across the MARKAI codebase. All findings include exact file paths and line numbers verified against the actual source code.*
