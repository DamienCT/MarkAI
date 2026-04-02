# MARKAI Project Audit Report

**Date:** 2026-04-01
**Scope:** Full codebase audit — security, database, architecture, performance, code quality, frontend
**Methodology:** Systematic file-by-file review across all services per `PROJECT_AUDIT_PROMPT.md`

---

## 1. Executive Summary

MARKAI is a well-architected system with clean LangGraph workflows, proper database normalization, and solid infrastructure patterns. However, this audit identified **3 CRITICAL**, **8 HIGH**, **15 MEDIUM**, and **20+ LOW** findings across security, database integrity, API correctness, and code quality. The top 3 risks are: (1) a **privilege escalation vulnerability** in the user update API that allows blind `setattr` on any schema field; (2) **sensitive data leakage** from brand guidelines on two API endpoints; and (3) a **frontend role default of "manager"** when the backend is unreachable, granting elevated UI permissions to all users. Most findings have straightforward fixes estimated at 1-4 hours each.

---

## 2. Critical Findings

### C-01: Privilege Escalation via Blind `setattr` on User Update
- **Location:** [users.py:252-298](backend/app/api/v1/users.py#L252-L298)
- **Description:** `PUT /{user_id}` and `PATCH /{user_id}` apply all fields from `UserUpdate` schema via `setattr(user, key, value)` without an allow-list. If `UserUpdate` includes fields like `entra_object_id`, `is_active`, or `role`, an admin can modify identity bindings, reactivate deactivated accounts, or escalate roles with no guard preventing self-escalation.
- **Impact:** An admin could bind their account to another user's Entra ID, or a compromised admin session could grant permanent access.
- **Evidence:** `for key, value in update_data.items(): setattr(user, key, value)` with no field filtering.
- **Fix:** Use an explicit allow-list of mutable fields:
  ```python
  MUTABLE_USER_FIELDS = {"display_name", "role", "is_active"}
  for key, value in update_data.items():
      if key in MUTABLE_USER_FIELDS:
          setattr(user, key, value)
  ```
  Additionally, prevent admins from modifying their own role.
- **Effort:** 1 hour

### C-02: Frontend Defaults to "manager" Role When Backend is Unreachable
- **Location:** [auth.ts:119-126](frontend/src/lib/auth.ts#L119-L126)
- **Description:** When the backend `/api/v1/users/me` call fails during the NextAuth `session` callback, `token.role` defaults to `"manager"` (level 80). Manager role can trigger research, strategy, and content workflows, create brands, manage approvals.
- **Impact:** During any backend outage, all authenticated users get manager-level UI access. Cached JWT sessions with "manager" role persist up to 7 days.
- **Fix:** Default to `"viewer"` instead of `"manager"`:
  ```typescript
  token.role = "viewer"; // was "manager"
  ```
- **Effort:** 15 minutes

### C-03: Sensitive Brand Guidelines Leaked on Two Endpoints
- **Location:** [brands.py:164](backend/app/api/v1/brands.py#L164), [brands.py:217](backend/app/api/v1/brands.py#L217)
- **Description:** `update_brand` and `complete_onboarding` return the brand object directly without calling `_strip_sensitive_guidelines()`. The `brand_guidelines` JSONB field may contain `access_token`, `api_key`, `refresh_token`, `webhook_url`, `client_secret` for social channel integrations.
- **Impact:** API keys and tokens for connected social accounts are exposed in API responses to any authenticated user with brand access.
- **Fix:** Apply `_strip_sensitive_guidelines(brand)` before return on both endpoints. Also note: `_strip_sensitive_guidelines` mutates the ORM object in-session, risking data loss if a subsequent `db.commit()` flushes the stripped values. Use `db.expunge(brand)` before mutating.
- **Effort:** 1 hour

---

## 3. High-Priority Findings

### H-01: Unauthenticated File Proxy Exposes All MinIO Objects
- **Location:** [files.py:20-60](backend/app/api/v1/files.py#L20-L60)
- **Description:** `GET /api/v1/files/{path}` requires no authentication. Anyone who can reach the backend can download any file from the `content-images`, `brand-assets`, or `markai-assets` MinIO buckets by guessing/enumerating object paths.
- **Impact:** All generated content images, brand logos, and assets are publicly accessible. UUIDs in paths provide obscurity but not security.
- **Fix:** Add `current_user: User = Depends(get_current_user)` or implement signed/time-limited URLs.
- **Effort:** 2 hours

### H-02: Incomplete Path Traversal Prevention in File Proxy
- **Location:** [files.py:26-27](backend/app/api/v1/files.py#L26-L27)
- **Description:** Only blocks `..` and leading `/`. Does not handle URL-encoded variants (`%2e%2e`), backslash traversal, or null bytes.
- **Fix:** Use `pathlib.PurePosixPath` for validation:
  ```python
  parts = PurePosixPath(file_path).parts
  if any(p in ('.', '..') for p in parts) or '\\' in file_path:
      raise HTTPException(403, "Invalid path")
  ```
- **Effort:** 1 hour

### H-03: JWKS Cache Never Invalidated — Authentication Outage on Key Rotation
- **Location:** [entra.py:56-59](backend/app/auth/entra.py#L56-L59)
- **Description:** `invalidate_jwks_cache()` is defined but never called. The JWKS client caches keys forever. Microsoft rotates signing keys every 24-48 hours.
- **Impact:** After key rotation, all JWT validation fails until the backend is restarted, causing complete authentication outage.
- **Fix:** Set the `lifespan` parameter on `PyJWKClient`:
  ```python
  _jwks_client = PyJWKClient(jwks_url, lifespan=3600)
  ```
- **Effort:** 15 minutes

### H-04: LiteLLM Proxy Timeout (120s) Kills Agent Requests Up to 600s
- **Location:** [litellm/config.yaml:96](litellm/config.yaml#L96), [llm.py:240](agents/shared/llm.py#L240)
- **Description:** LiteLLM config sets `request_timeout: 120`. Agent code computes dynamic timeouts up to 600s for large `max_tokens` values. The proxy kills upstream LLM calls at 120s regardless of client timeout.
- **Impact:** Strategy document generation (max_tokens=16384) and other large requests are silently truncated at 120s.
- **Fix:** Increase `request_timeout` in `litellm/config.yaml` to 600:
  ```yaml
  request_timeout: 600
  ```
- **Effort:** 15 minutes

### H-05: Reviewer Not Recorded on Approval Decisions
- **Location:** [approvals.py:148-192](backend/app/api/v1/approvals.py#L148-L192), [approval_service.py:62-93](backend/app/services/approval_service.py#L62-L93)
- **Description:** Neither the endpoint nor service sets `approval.reviewer_id` to `current_user.id`. The reviewer is never recorded.
- **Impact:** Audit trail is incomplete — no record of who approved/rejected content.
- **Fix:** Pass `current_user.id` to `resolve_approval()` and set `approval.reviewer_id` before commit.
- **Effort:** 30 minutes

### H-06: No Content Chain Depth Limit for Sequential Generation
- **Location:** [worker.py:469-504](agents/worker.py#L469-L504)
- **Description:** Sequential content chaining increments `chain_depth` but never checks it against any limit. `MAX_CHAIN_DEPTH = 2` only applies to the adaptation→planning loop. If a bug causes items to never leave "queued" status, chaining could loop indefinitely.
- **Fix:** Add `MAX_CONTENT_CHAIN_DEPTH = 200` guard before publishing the next content item.
- **Effort:** 30 minutes

### H-07: Timeout Retry Bypass — `TimeoutError` Not Classified as Retryable
- **Location:** [llm.py:69-75, 271-273](agents/shared/llm.py#L69-L75)
- **Description:** `chat_completion` catches `httpx.TimeoutException` and re-raises as stdlib `TimeoutError`. But `_is_retryable` only checks for `httpx.TimeoutException`. Timeouts — the most common transient error — are never retried.
- **Fix:** Add `isinstance(exc, TimeoutError)` to `_is_retryable`, or don't re-wrap the exception.
- **Effort:** 15 minutes

### H-08: User.name vs display_name Frontend/Backend Mismatch
- **Location:** [types/index.ts:238](frontend/src/types/index.ts#L238) vs [auth/models.py:21](backend/app/auth/models.py#L21)
- **Description:** Frontend `User` interface uses `name: string` but backend model/schema uses `display_name`. Also `last_login` vs `last_login_at`, and `brand_ids` doesn't exist on backend.
- **Impact:** User names render as `undefined` throughout the frontend.
- **Fix:** Align frontend interface field names with backend schema.
- **Effort:** 1 hour

---

## 4. Medium-Priority Findings

### M-01: ORM ForeignKey Definitions Missing ON DELETE Actions
- **Location:** All models in [backend/app/models/](backend/app/models/)
- **Description:** `init.sql` defines `ON DELETE CASCADE`/`SET NULL` on many FKs. None of the ORM `ForeignKey()` calls include `ondelete=`. This can cause `IntegrityError` if ORM tries operations that conflict with DB-level cascades.
- **Fix:** Add `ondelete="CASCADE"` or `ondelete="SET NULL"` to each `ForeignKey()`.
- **Effort:** 2 hours

### M-02: PromptVersion Schema Mismatches
- **Location:** [prompt_version.py:35-37](backend/app/models/prompt_version.py#L35-L37)
- **Description:** `performance_score`: ORM `Numeric(7,4)` vs DB `NUMERIC(5,4)`. `a_b_group`: ORM `String(255)` vs DB `VARCHAR(1)`.
- **Fix:** Match ORM to DB: `Numeric(5,4)` and `String(1)`.
- **Effort:** 15 minutes

### M-03: Multiple VARCHAR Length Mismatches Between ORM and DB
- **Location:** Various models
- **Description:** `AgentRun.agent_type`: 255 vs 100. `AgentRun.trigger`: 255 vs 100. `EngagementMetric.channel`: 255 vs 50. `AuditLog.action`: 255 vs 100. `AuditLog.entity_type`: 255 vs 100. `ScheduledJobLog.job_type`: 255 vs 100. `Campaign.objective`: 255 vs 100.
- **Fix:** Batch-fix all to match `init.sql` values.
- **Effort:** 1 hour

### M-04: No Alembic Migration Files Exist
- **Location:** [backend/alembic/versions/](backend/alembic/versions/) (empty)
- **Description:** Schema is managed only via `init.sql`. No version-controlled migration path.
- **Fix:** Generate initial Alembic migration with `alembic revision --autogenerate`.
- **Effort:** 4 hours

### M-05: NATS Stream Subjects Misaligned Between Backend and Agents
- **Location:** [nats_service.py:19-31](backend/app/services/nats_service.py#L19-L31) vs [worker.py:794-802](agents/worker.py#L794-L802)
- **Description:** Backend declares 10 subjects (`publish.>`, `engagement.>`, `brand.>` extra). Agents only subscribe to 7. Messages on the 3 extra subjects have no consumer.
- **Fix:** Either add handlers in the worker or remove unused subjects from backend config.
- **Effort:** 1 hour

### M-06: Missing English Language Instruction in Content Generation Prompts
- **Location:** [content/nodes.py](agents/workflows/content/nodes.py) — `generate_hook`, `generate_caption`, `generate_hashtags`, `adapt_platforms`
- **Description:** System prompts do not instruct "Write in English." Non-English brand data may cause LLM to generate in that language.
- **Fix:** Add "Write everything in English." to each content generation system prompt.
- **Effort:** 30 minutes

### M-07: `_strip_sensitive_guidelines` Mutates ORM Object In-Session
- **Location:** [brands.py:62-63](backend/app/api/v1/brands.py#L62-L63)
- **Description:** Sets `brand.brand_guidelines = cleaned` on the live ORM instance. A subsequent `db.commit()` in the same request could flush the stripped version to the database, permanently deleting secrets.
- **Fix:** `db.expunge(brand)` before mutation, or serialize to dict manually.
- **Effort:** 30 minutes

### M-08: Calendar Reorder Endpoint Has No Batch Size Limit
- **Location:** [calendar.py:166](backend/app/api/v1/calendar.py#L166)
- **Description:** `POST /reorder` accepts unlimited `items` list. DoS risk via excessive DB operations.
- **Fix:** Add `max_length=500` to the list field.
- **Effort:** 15 minutes

### M-09: Approval Status Bypasses Content Service Validation
- **Location:** [approval_service.py:86-89](backend/app/services/approval_service.py#L86-L89)
- **Description:** When approved/rejected, calendar item status is set directly without calling `_validate_transition()`.
- **Fix:** Add transition validation before setting status.
- **Effort:** 1 hour

### M-10: `failed → scheduled` Status Transition Bypasses Review
- **Location:** [content_service.py:84](backend/app/services/content_service.py#L84)
- **Description:** `VALID_TRANSITIONS` allows `"failed": ["scheduled"]`, bypassing the review flow.
- **Fix:** Change to `"failed": ["queued"]` to force re-processing.
- **Effort:** 15 minutes

### M-11: SSE Notification Polling — N Queries Every 10 Seconds
- **Location:** [notifications.py:58-101](backend/app/api/v1/notifications.py#L58-L101)
- **Description:** Each connected client polls the DB every 10 seconds. Does not scale.
- **Fix:** Use Valkey pub/sub or NATS to push notifications to SSE connections.
- **Effort:** 8 hours

### M-12: next-auth@4 and @auth/core Conflict
- **Location:** [package.json:13,33](frontend/package.json#L13)
- **Description:** `next-auth` v4 has its own auth core; `@auth/core` is for v5. Both installed creates type conflicts.
- **Fix:** Remove `@auth/core` from dependencies.
- **Effort:** 15 minutes

### M-13: Agents Health Check Uses `pgrep` Instead of HTTP
- **Location:** [docker-compose.yml:302](docker-compose.yml#L302)
- **Description:** `pgrep -f 'python -m worker'` only checks process existence, not actual health (NATS connection, deadlock state).
- **Fix:** Add a lightweight HTTP health endpoint to the agents worker.
- **Effort:** 2 hours

### M-14: SSRF Risk in Product Image Downloads
- **Location:** [content/nodes.py:818-820](agents/workflows/content/nodes.py#L818-L820)
- **Description:** `_replace_product_in_generated_image` downloads from arbitrary URLs without validation. If product `image_urls` contain internal network URLs, this enables SSRF.
- **Fix:** Validate URLs against HTTPS-only, public hostnames. Reject private IP ranges.
- **Effort:** 2 hours

### M-15: `/api/v1/providers/active` Has No Authentication
- **Location:** [providers.py:73-82](backend/app/api/v1/providers.py#L73-L82)
- **Description:** Returns active model IDs per category without auth. Only exposes model name strings (not keys), but reveals infrastructure details.
- **Fix:** Add authentication or move to internal-only route.
- **Effort:** 30 minutes

---

## 5. Low-Priority Findings

| ID | Location | Description |
|---|---|---|
| L-01 | [worker.py:202-209](agents/worker.py#L202-L209) | Image regeneration failures silently swallowed — no user feedback |
| L-02 | [llm.py:27-38](agents/shared/llm.py#L27-L38) | Shared httpx client creation has theoretical race condition |
| L-03 | [llm.py:337-388](agents/shared/llm.py#L337-L388) | Direct OpenAI API for images bypasses LiteLLM cost tracking |
| L-04 | [llm.py:163-171](agents/shared/llm.py#L163-L171) | `parse_llm_json` auto-unwraps single-key dicts, may corrupt valid data |
| L-05 | [worker.py:763-771](agents/worker.py#L763-L771) | Timeout NAK retries waste 2.5 hours of compute (5 × 30-min timeouts) |
| L-06 | [planning/nodes.py:318-321](agents/workflows/planning/nodes.py#L318-L321) | Dead code — computed values never assigned or used |
| L-07 | [planning/nodes.py:534](agents/workflows/planning/nodes.py#L534) | Sets status "planned" but DB function hardcodes "queued" — misleading |
| L-08 | [planning/nodes.py:348](agents/workflows/planning/nodes.py#L348) | Dedup context limited to last 60 items — may miss older duplicates |
| L-09 | [content/graph.py:70-72](agents/workflows/content/graph.py#L70-L72) | Final conditional edge is redundant — both paths go to END |
| L-10 | [content/nodes.py:524](agents/workflows/content/nodes.py#L524) | LIKE pattern doesn't escape `%` and `_` wildcards in product names |
| L-11 | [models/engagement.py:43-44](backend/app/models/engagement.py#L43-L44) | `fetched_at` missing `server_default=func.now()` |
| L-12 | [auth/models.py:106-107](backend/app/auth/models.py#L106-L107) | `ScheduledJobLog.started_at` missing `server_default=func.now()` |
| L-13 | [models/base.py:10-15](backend/app/models/base.py#L10-L15) | Backend engine missing `pool_pre_ping=True` (stale connections on DB restart) |
| L-14 | [minio_service.py:23](backend/app/services/minio_service.py#L23) | `secure=False` hardcoded — acceptable for Docker-internal but not configurable |
| L-15 | [docker-compose.yml:123](docker-compose.yml#L123) | Valkey health check leaks password in process list |
| L-16 | [package.json:35](frontend/package.json#L35) | `postcss` in dependencies instead of devDependencies |
| L-17 | [stores/brand-store.ts:11-14](frontend/src/stores/brand-store.ts#L11-L14) | Duplicate `ChannelConfig` type shadows the one in types/index.ts |
| L-18 | [types/index.ts:311-319](frontend/src/types/index.ts#L311-L319) | `Notification` type field names don't match backend (`type`→`notification_type`, `message`→`body`, `read`→`is_read`) |
| L-19 | [types/index.ts:103-104](frontend/src/types/index.ts#L103-L104) | `Content` type has deprecated `title` field and fields that live on `CalendarItem` |
| L-20 | [scheduler/__init__.py:11-28](backend/app/scheduler/__init__.py#L11-L28) | `get_app_setting` silently swallows all exceptions — no logging |
| L-21 | [content.py:126](backend/app/api/v1/content.py#L126) | `transition` takes `new_status` as query param instead of body |
| L-22 | [analytics.py:62](backend/app/api/v1/analytics.py#L62) | `days` parameter has no upper bound — could scan huge time ranges |

---

## 6. Remediation Plan

### Phase 1: Critical Security Fixes (Day 1) — ~4 hours
| Priority | Finding | Fix | Effort |
|---|---|---|---|
| 1 | C-01 | Add allow-list to user update `setattr` loop | 1h |
| 2 | C-02 | Change frontend role default from "manager" to "viewer" | 15m |
| 3 | C-03 | Add `_strip_sensitive_guidelines` to update/onboarding + fix ORM mutation | 1h |
| 4 | H-03 | Set JWKS `lifespan=3600` | 15m |
| 5 | H-04 | Increase LiteLLM `request_timeout` to 600 | 15m |
| 6 | H-07 | Fix `_is_retryable` to include `TimeoutError` | 15m |

### Phase 2: High-Priority Fixes (Day 2-3) — ~8 hours
| Priority | Finding | Fix | Effort |
|---|---|---|---|
| 7 | H-01/H-02 | Add auth to file proxy + fix path traversal | 3h |
| 8 | H-05 | Record reviewer_id on approval decisions | 30m |
| 9 | H-06 | Add content chain depth limit | 30m |
| 10 | H-08 | Align frontend User type with backend schema | 1h |
| 11 | M-01 | Add `ondelete=` to all ORM ForeignKeys | 2h |
| 12 | M-02/M-03 | Fix all ORM column type mismatches | 1h |

### Phase 3: Medium-Priority Improvements (Week 2) — ~20 hours
| Priority | Finding | Fix | Effort |
|---|---|---|---|
| 13 | M-04 | Set up Alembic migrations | 4h |
| 14 | M-05 | Align NATS subjects between backend and agents | 1h |
| 15 | M-06 | Add English language instruction to all content prompts | 30m |
| 16 | M-07 | Fix `_strip_sensitive_guidelines` ORM mutation risk | 30m |
| 17 | M-08 | Add batch size limits to reorder/batch endpoints | 30m |
| 18 | M-09/M-10 | Fix status transition validation gaps | 1.5h |
| 19 | M-11 | Replace SSE polling with pub/sub | 8h |
| 20 | M-12 | Remove `@auth/core` dependency | 15m |
| 21 | M-13 | Add HTTP health endpoint to agents worker | 2h |
| 22 | M-14 | Add URL validation for image downloads (SSRF) | 2h |

### Phase 4: Low-Priority Cleanup (Ongoing)
- Fix frontend type mismatches (L-18, L-19)
- Add `server_default` to ORM timestamp columns (L-11, L-12)
- Add `pool_pre_ping=True` to backend engine (L-13)
- Clean up dead code in planning nodes (L-06)
- Remove dead graph edges (L-09)

---

## 7. Architecture Recommendations

1. **Consolidate duplicated sanitization** — `agents/shared/sanitize.py` and `backend/app/api/v1/intelligence.py` have identical prompt injection patterns. Extract to a shared package or keep a single source of truth.

2. **Consolidate channel constants** — `ALL_CHANNELS` is defined in `backend/app/models/brand.py`, `frontend/src/types/index.ts`, and `agents/workflows/planning/nodes.py`. Keep one authoritative source (backend) and derive others.

3. **Split `worker.py`** — At 878 lines with complex chaining logic, consider extracting: (a) message handlers into separate modules, (b) chaining/skip logic into a `ChainManager` class, (c) image regeneration into its own handler module.

4. **Add a `ContentDetailResponse` schema** — The frontend `Content` type includes fields from `CalendarItem`. Create a joined response schema on the backend to formalize this contract.

5. **Consider Valkey pub/sub for notifications** — Replace the 10-second polling SSE with Valkey `SUBSCRIBE` per user channel. This eliminates N queries/10s and enables real-time delivery.

---

## 8. Testing Recommendations

### Priority 1: Security Tests
- Test privilege escalation on user update endpoint
- Test path traversal variants on file proxy
- Test JWKS rotation handling
- Test role enforcement on all protected endpoints

### Priority 2: Integration Tests
- Brand activation pipeline end-to-end (with mocked LLM)
- Content status transition state machine coverage
- Approval workflow with reviewer recording
- NATS message publish/consume round-trip

### Priority 3: Workflow Tests
- Planning calendar batch loop termination
- Content generation with all error paths
- Dedup context rebuild correctness
- Image generation fallback chain

### Priority 4: Frontend Tests
- Type alignment validation (automated schema comparison)
- Auth flow: token refresh, error states, role display
- KanbanBoard drag-and-drop status transitions

---

## Known Issues Verified

| # | Claim from Audit Prompt | Verdict |
|---|---|---|
| 1 | Dedup context updated between batches | **CONFIRMED FIXED** — `_build_dedup_context` combines existing + generated items |
| 2 | French text in old data | **PARTIALLY FIXED** — Some content prompts still lack "Write in English" instruction |
| 3 | Image model fallback chain | **CONFIRMED WORKING** — Falls back to dall-e-3 on model failure |
| 4 | Calendar batch LLM response handling | **CONFIRMED** — Handles single items, wrapped dicts, and bare arrays |
| 5 | "planned" vs "queued" status | **NO RUNTIME BUG** — `store_calendar_items` hardcodes "queued", but code is misleading |
| 6 | MinIO `secure=False` | **CONFIRMED** — Internal Docker network, acceptable but not configurable |
| 7 | SSE polling inefficiency | **CONFIRMED** — 10-second DB poll per client |
| 8 | LiteLLM timeout conflict | **CONFIRMED** — 120s proxy timeout vs 600s agent timeout |
| 9 | No Alembic migrations | **CONFIRMED** — `versions/` directory is empty |

---

*Generated from comprehensive codebase audit on 2026-04-01.*
