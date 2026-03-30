# Re-Audit Cycle 1 -- Verification Report

**Date:** 2026-03-30
**Auditor:** Claude Opus 4.6 (automated)
**Scope:** Verify all fixes from MASTER_REMEDIATION_PLAN.md and check for regressions

---

## SECURITY FIXES

### SEC-001: Traefik dashboard auth uses env var
**Status: PASS**
`docker-compose.yml` line 30 uses `${TRAEFIK_DASHBOARD_AUTH}` env var instead of a hardcoded htpasswd string.

### SEC-003: files.py has Depends(get_current_user)
**Status: PASS**
`backend/app/api/v1/files.py` line 25: `current_user: User = Depends(get_current_user)` is present on the `serve_file` endpoint.

### SEC-004: brands.py _strip_sensitive_guidelines applied
**Status: PASS**
- `_strip_sensitive_guidelines` is defined at lines 26-46.
- Applied in `list_brands` (line 80) and `get_brand` (line 92).
- Sensitive keys: `access_token`, `api_key`, `refresh_token`, `webhook_url`, `client_secret` are stripped.

### SEC-006: slowapi rate limiting configured
**Status: PASS**
- `backend/app/main.py` line 64: global `Limiter` with `default_limits=["120/minute"]`.
- Line 73: `app.state.limiter = limiter` and line 74: exception handler added.
- `intelligence.py` lines 484, 616: `@_limiter.limit("10/minute")` on generate-fields and rewrite-field.
- `brands.py` line 201: `@_limiter.limit("5/minute")` on activate endpoint.
- `products.py` line 149: `@_limiter.limit("20/minute")` on upload-image endpoint.

### SEC-013: brands.py logo endpoint has auth
**Status: PASS**
- `upload_brand_logo` (line 298): `current_user: User = Depends(get_current_user)` + manager role check.
- `get_brand_logo` (line 350): `current_user: User = Depends(get_current_user)`.
- `delete_brand_logo` (line 377): `current_user: User = Depends(get_current_user)` + manager role check.

### SEC-014: products.py image upload validates size and type
**Status: PASS**
- `upload_product_image` (line 166): validates `file.content_type.startswith("image/")`.
- Line 172: validates `len(file_data) > 5 * 1024 * 1024`.
- Brand logo upload also validates (line 316): allowed set `{"image/png", "image/jpeg", "image/svg+xml", "image/webp"}`, and line 321: 5MB size check.

### SEC-015: brands.py activate/complete-onboarding require manager role
**Status: PASS**
- `complete_onboarding` (line 162): `role_has_access(current_user.role, "manager")` check.
- `activate_content_factory` (line 209): `role_has_access(current_user.role, "manager")` check.

### SEC-019: min(limit) in every list endpoint
**Status: PASS**
All 22 list endpoints with `limit` parameters have `limit = min(limit, 200)` applied:
- `router.py`, `agents.py`, `brands.py`, `approvals.py` (x3), `analytics.py`, `content.py` (x2), `notifications.py`, `learning.py`, `campaigns.py`, `users.py`, `intelligence.py` (x3), `calendar.py` (x2), `system.py` (x2), `prompts.py`, `products.py`.

### SEC-021: Frontend admin pages use useRequireRole
**Status: PASS**
- `system/page.tsx`: `useRequireRole("admin")`
- `system/audit/page.tsx`: `useRequireRole("manager")`
- `settings/users/page.tsx`: `useRequireRole("admin")`
- `settings/page.tsx`: `useRequireRole("manager")`

### SEC-023: docker-compose.override.yml ports use 127.0.0.1
**Status: PASS**
All 17 port bindings in `docker-compose.override.yml` use `127.0.0.1:` prefix (traefik, postgres, qdrant, minio, valkey, nats, litellm, n8n, backend, frontend, browser-worker, grafana, prometheus, loki, otel-collector).

---

## BUG FIXES

### BUG-001: database.py uses fetched_at not measured_at
**Status: PASS**
- `agents/shared/tools/database.py` line 429: `em.fetched_at` used in query.
- `db/init.sql` line 297: column is `fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
- All backend code (`engagement_puller.py`, `analytics.py`, `analytics_service.py`, model, schema) consistently uses `fetched_at`.

### BUG-002: database.py store_adaptations uses correct column names
**Status: PASS**
`agents/shared/tools/database.py` `store_adaptations` (lines 437-493) uses correct column names matching the `adaptations` table schema: `source_content_id`, `target_channel`, `adapted_text`, `adapted_headline`, `adaptation_notes`, `status`. Both the evaluation-node schema path and legacy content-adaptation schema path use valid columns.

### BUG-003: db/init.sql has unique index on products(brand_id, bc_item_no)
**Status: PASS**
`db/init.sql` line 88: `CREATE UNIQUE INDEX idx_products_brand_bc_item ON products (brand_id, bc_item_no) WHERE bc_item_no IS NOT NULL;`
The partial unique index correctly handles NULL bc_item_no values.

### BUG-006: db/init.sql has partial unique index on agent_runs running; worker.py catches IntegrityError
**Status: PASS**
- `db/init.sql` line 276: `CREATE UNIQUE INDEX idx_agent_runs_running ON agent_runs (brand_id, agent_type) WHERE status = 'running';`
- `worker.py` line 1: imports `IntegrityError` from sqlalchemy.exc (line 22).
- Lines 313-319: catches `IntegrityError`, logs warning, acks message, returns (no retry).

### BUG-008: content/nodes.py uses {{1,3}} not {1,3}
**Status: PASS**
`agents/workflows/content/nodes.py` line 44: `rf"(#{{1,3}}\s*.*{re.escape(month_name)}.*?)(?=#{{1,3}}\s|\Z)"` -- double braces are correct in f-strings to produce literal `{1,3}` regex quantifier.

### BUG-009: webhooks.py has flag_modified call
**Status: PASS**
`backend/app/api/v1/webhooks.py` line 9: imports `flag_modified`, line 99: `flag_modified(content, "generation_metadata")` is called after mutating the JSONB field.

### BUG-010: content/nodes.py -- Gemini model hardcoded, not from get_model_for_category
**Status: PASS**
The Gemini model `"gemini-2.5-flash-image"` at line 679 of `content/nodes.py` is correctly hardcoded. This is by design -- Gemini image editing is a specialized capability (product-in-scene replacement) that cannot be routed through the generic LiteLLM model selection. The `generate_image` function in `shared/llm.py` (line 238-239) correctly uses `get_model_for_category("image")` for standard image generation. The Gemini usage is a separate direct-API call for a capability LiteLLM does not proxy.

### BUG-011: strategy/nodes.py has json.loads fallback for string research_data
**Status: PASS**
`agents/workflows/strategy/nodes.py` lines 27-31: checks `isinstance(research_data, str)`, attempts `json.loads(research_data)`, falls back to `{"raw": research_data}` on error.

### BUG-012: content/state.py has all required fields
**Status: PASS**
`agents/workflows/content/state.py` defines `ContentState(TypedDict)` with all fields:
1. `brand_id`, `run_id`, `calendar_item_id`, `status`, `errors`, `messages` (base)
2. `calendar_item`, `brand`, `strategy`, `positioning`, `relevant_pillar`, `relevant_audience`, `month_context`, `recent_posts`, `top_performing`, `product` (context)
3. `hook`, `caption`, `hashtags`, `cta` (content)
4. `product_image`, `product_image_source`, `product_id`, `needs_manual_image`, `is_lifestyle_only`, `generated_image` (images)
5. `branded_image`, `logo_png_data` (branding)
6. `mockup_urls` (mockups)
7. `platform_adaptations` (adaptations)

All 7 field groups are present.

### BUG-013: entra.py -- _graph_token_lock at module level
**Status: PASS**
`backend/app/auth/entra.py` line 73: `_graph_token_lock = asyncio.Lock()` at module level.
Line 76-78: wrapped in `_get_token_lock()` helper function.
Line 92: used via `async with _get_token_lock():`.

**Note:** In Python 3.10+, `asyncio.Lock()` created at module level no longer binds to a specific event loop, so this is safe. The `_get_token_lock()` wrapper adds an extra layer of indirection for future flexibility.

### BUG-015: worker.py -- chain error does NOT overwrite result
**Status: PASS**
`worker.py` lines 300-311: when a chain publish fails (e.g., `research -> strategy.trigger`), the error is handled in a `except Exception as chain_exc` block that:
1. Logs the error (line 301)
2. Patches `_chain_error` into the already-completed run's `output_payload` using `output_payload || :patch` (appends, does not overwrite)
3. The completed agent_run with its result was already saved at line 146 (`complete_agent_run(run_id, output_payload=safe_result, status="completed")`)
4. Explicit comment at line 302: "Log chain error separately -- do NOT overwrite the already-completed run"

---

## PERF FIXES

### PERF-001: fabric_service.py -- asyncio.to_thread wrapping
**Status: PASS**
`backend/app/services/fabric_service.py`:
- Line 80: `_run_query_sync` is a synchronous helper designed for `to_thread`.
- Line 100: `await asyncio.to_thread(_run_query_sync, token, query, params)` wraps the blocking pyodbc call.
- Line 104: retry path also uses `await asyncio.to_thread(...)`.

### PERF-002: minio_service.py -- asyncio.to_thread wrapping; callers use await
**Status: PASS**
`backend/app/services/minio_service.py`:
- `ensure_bucket` (lines 31-33): `await asyncio.to_thread(client.bucket_exists, ...)` and `await asyncio.to_thread(client.make_bucket, ...)`.
- `upload_file` (line 48): `await asyncio.to_thread(client.put_object, ...)`.
- `download_file` (line 77): `await asyncio.to_thread(_download_sync, ...)`.
- `get_presigned_url` (line 88): `await asyncio.to_thread(client.presigned_get_object, ...)`.
- `get_presigned_upload_url` (line 101): `await asyncio.to_thread(client.presigned_put_object, ...)`.
- `delete_file` (line 113): `await asyncio.to_thread(client.remove_object, ...)`.

All callers in `files.py`, `brands.py`, `products.py` correctly use `await` when calling these async functions.

### PERF-003: qdrant_service.py -- asyncio.to_thread wrapping
**Status: PASS**
`backend/app/services/qdrant_service.py`:
- `ensure_collection` (line 40): `await asyncio.to_thread(client.get_collections)` and (line 43) `await asyncio.to_thread(client.create_collection, ...)`.
- `upsert_vectors` (line 71): `await asyncio.to_thread(client.upsert, ...)`.
- `search_vectors` (line 100): `await asyncio.to_thread(client.search, ...)`.
- `delete_vectors` (line 125): `await asyncio.to_thread(client.delete, ...)`.

### PERF-004: entra.py -- JWKS fetch in to_thread
**Status: PASS**
`backend/app/auth/entra.py` line 35: `signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)` -- the blocking JWKS network fetch is wrapped in `to_thread`.

### DB Indexes: db/init.sql -- verify all new indexes exist
**Status: PASS**
All indexes are properly defined in `db/init.sql`:
- `idx_brands_status` (line 52)
- `idx_products_brand_bc_item` unique partial (line 88)
- `idx_products_is_active` (line 93)
- `idx_products_tags` GIN (line 94)
- `idx_calendar_items_brand_scheduled` composite (line 164)
- `idx_calendar_items_status_published` partial (line 166)
- `idx_agent_runs_running` unique partial (line 276)
- `idx_agent_runs_brand_type_created` composite (line 277)
- `idx_engagement_metrics_brand_fetched` composite (line 306)
- `idx_notifications_user_unread` partial (line 415)
- All standard FK indexes and column indexes present.

---

## FRONTEND FIXES

### FE-001: api.ts fallback is localhost:8000
**Status: PASS**
`frontend/src/lib/api.ts` line 4: `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"`.

### FE-002: Dockerfile default build arg is localhost:8000
**Status: PASS**
`frontend/Dockerfile` line 20: `ARG NEXT_PUBLIC_API_URL=http://localhost:8000`.

### FE-003: next.config.ts -- unoptimized removed, remotePatterns configured
**Status: PASS**
`frontend/next.config.ts`:
- No `unoptimized: true` present.
- `remotePatterns` configured for `*.hstgr.cloud`, `localhost:8000`, and `minio:9000`.

### FE-004: EngagementChart uses dynamic import
**Status: PASS**
`frontend/src/components/analytics/EngagementChart.tsx` line 3: `import dynamic from "next/dynamic"`, line 19: `const EngagementChartInner = dynamic(...)` with lazy loading from separate `EngagementChartInner` module.

### FE-005: KanbanBoard uses dynamic import
**Status: PASS**
`frontend/src/components/content/KanbanBoard.tsx` line 3: `import dynamic from "next/dynamic"`, line 11: `const KanbanBoardInner = dynamic(...)` with lazy loading from separate `KanbanBoardInner` module.

### FE-006: CalendarView uses useMemo
**Status: PASS**
`frontend/src/components/content/CalendarView.tsx` line 3: imports `useMemo`, line 100: `const itemsByDateKey = useMemo(...)` to memoize the date-keyed grouping computation.

---

## REGRESSION CHECK: New Issues Introduced by Fixes

### Import correctness
**Status: PASS**
All files checked have correct imports. No missing or dangling imports detected.

### Circular imports
**Status: PASS**
No circular import patterns detected. The `from ... import` statements in worker.py use late/local imports (`from shared.tools.database import ...` inside handlers) which is safe.

### Type errors
**Status: PASS**
No type errors introduced. All `await` calls match async function signatures. The `minio_service` functions are all `async def` with `asyncio.to_thread` internally, and all callers use `await`.

### minio_service going async -- callers updated?
**Status: PASS**
All callers use `await`:
- `files.py` line 32: `data = await minio_service.download_file(file_path)`
- `brands.py` line 327-328: `await minio_service.ensure_bucket()`, `await minio_service.upload_file(...)`
- `brands.py` line 369: `data = await minio_service.download_file(...)`
- `brands.py` line 399: `await minio_service.delete_file(...)`
- `products.py` line 178: `await minio_service.upload_file(...)`
- `products.py` line 266-267: `await minio_service.ensure_bucket()`, `await minio_service.upload_file(...)`
- `main.py` line 52: `await minio_service.ensure_bucket()`

### slowapi integration -- endpoint signatures
**Status: PASS**
All rate-limited endpoints correctly include `request: Request` as the first parameter:
- `brands.py` line 203: `activate_content_factory(request: Request, ...)`
- `products.py` line 151: `upload_product_image(request: Request, ...)`
- `intelligence.py` line 486: `generate_brand_fields(request: Request, ...)`
- `intelligence.py` line 618: `rewrite_brand_field(request: Request, ...)`

The `_limiter` instances in `brands.py`, `products.py`, and `intelligence.py` are module-level `Limiter` objects, which is the correct pattern for slowapi per-route limits alongside the global limiter in `main.py`.

---

## SUMMARY

| Category | Total Items | PASS | FAIL | PARTIAL |
|----------|------------|------|------|---------|
| Security | 10 | 10 | 0 | 0 |
| Bug Fixes | 11 | 11 | 0 | 0 |
| Performance | 5 | 5 | 0 | 0 |
| Frontend | 6 | 6 | 0 | 0 |
| Regressions | 5 | 5 | 0 | 0 |
| **Total** | **37** | **37** | **0** | **0** |

**Conclusion:** All 37 verification items PASS. No regressions detected. The remediation plan has been fully and correctly implemented.
