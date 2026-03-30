# Phase 1: Backend Audit Report

**Date:** 2026-03-30
**Scope:** All 86 Python files under `D:\MarkAI\backend\`
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The MARKAI backend is a well-structured FastAPI application with async SQLAlchemy, NATS JetStream, and several integrations (Microsoft Entra ID, MinIO, Qdrant, Fabric/Power BI, social platforms). The codebase is generally clean with good production safety checks. However, the audit identified **47 findings** across all severity levels.

**Critical:** 3 | **High:** 12 | **Medium:** 19 | **Low:** 13

---

## CRITICAL Findings

### C1. Blocking synchronous I/O in async context (fabric_service.py)
- **File:** `backend/app/services/fabric_service.py`, lines 79-100
- **Category:** Performance / Reliability
- **Description:** `execute_sql()` is declared `async` but calls `pyodbc.connect()`, `cursor.execute()`, and `cursor.fetchall()` -- all blocking synchronous operations. pyodbc does not support async. This blocks the entire asyncio event loop during every Fabric SQL query, stalling all concurrent requests.
- **Proposed fix:** Wrap the synchronous pyodbc calls in `asyncio.to_thread()` or use `loop.run_in_executor()`:
  ```python
  import asyncio
  rows = await asyncio.to_thread(_sync_execute, query, params, token)
  ```

### C2. Blocking synchronous I/O in async context (minio_service.py)
- **File:** `backend/app/services/minio_service.py`, all functions
- **Category:** Performance / Reliability
- **Description:** All MinIO operations (`upload_file`, `download_file`, `get_presigned_url`, `delete_file`, `ensure_bucket`) are synchronous (the `minio` library is sync-only) but are called from async handlers and scheduler jobs. When called from async route handlers (brands.py logo upload/download, products.py image upload, files.py proxy), they block the event loop.
- **Proposed fix:** Wrap all MinIO calls in `asyncio.to_thread()` at the call sites, or create async wrapper functions.

### C3. Blocking synchronous I/O in async context (qdrant_service.py)
- **File:** `backend/app/services/qdrant_service.py`, all functions
- **Category:** Performance / Reliability
- **Description:** `QdrantClient` is the synchronous client. All operations (`upsert_vectors`, `search_vectors`, `delete_vectors`, `ensure_collection`) block the event loop. Should use `qdrant_client.AsyncQdrantClient` instead.
- **Proposed fix:** Replace `QdrantClient` with `AsyncQdrantClient` from `qdrant_client`.

---

## HIGH Findings

### H1. JWT JWKS fetch is synchronous, blocks event loop (entra.py)
- **File:** `backend/app/auth/entra.py`, line 35
- **Category:** Performance / Bug
- **Description:** `client.get_signing_key_from_jwt(token)` is a synchronous call that performs an HTTP request to fetch JWKS keys (on first call or cache miss). This blocks the event loop during authentication of every request when keys need to be fetched.
- **Proposed fix:** Use `await asyncio.to_thread(client.get_signing_key_from_jwt, token)` or use an async JWKS library.

### H2. Unauthenticated file proxy endpoint (files.py)
- **File:** `backend/app/api/v1/files.py`, lines 20-52
- **Category:** Security
- **Description:** The `/api/v1/files/{file_path:path}` endpoint serves any file from MinIO without authentication. While the comment explains this is for `<img>` tags, it allows unauthenticated access to all files in the MinIO bucket. An attacker who discovers or guesses file paths can access brand logos, product images, and any other stored files.
- **Proposed fix:** Either (a) use presigned MinIO URLs with TTL for `<img>` tags, or (b) add authentication via query-string tokens, or (c) restrict access to specific path prefixes only (e.g., only `brands/*/logos/` and `products/*/gallery/`).

### H3. No file size limit enforcement before reading upload (products.py)
- **File:** `backend/app/api/v1/products.py`, lines 158-162
- **Category:** Security / Reliability
- **Description:** `upload_product_image` reads the entire file into memory (`await file.read()`) without checking content type or size first. A malicious user could upload a multi-GB file, causing OOM. The brand logo upload (brands.py:281) has a 5MB check but only AFTER reading the full file into memory.
- **Proposed fix:** Add a max file size middleware or check `Content-Length` header before reading. Use streaming upload to MinIO for large files.

### H4. No input validation on `limit` query parameters (multiple files)
- **File:** Multiple API endpoints
- **Category:** Security / Performance
- **Description:** Most list endpoints accept `limit` as an integer query parameter with no upper bound. A user could pass `limit=999999` and trigger unbounded data fetches. Affected endpoints include: `list_brands` (100 default), `list_content`, `list_campaigns`, `list_calendar_items` (200 default), `list_products`, `list_prompts`, `list_approvals`, `list_users`, `get_top_content`, `list_agent_runs`, etc.
- **Proposed fix:** Add `Query(le=500)` or similar upper bounds on all `limit` parameters.

### H5. Platform credentials stored in brand_guidelines JSONB (publish_service.py, engagement_puller.py)
- **File:** `backend/app/services/publish_service.py`, lines 14-59; `backend/app/scheduler/engagement_puller.py`, lines 82-98
- **Category:** Security
- **Description:** Social platform API tokens (Meta, LinkedIn, TikTok, X) are stored inside the `brand_guidelines` JSONB column. These tokens are included in every `BrandResponse` serialization (the schema includes `brand_guidelines: dict = {}`), meaning access tokens are exposed to any authenticated user via `GET /api/v1/brands/` and `GET /api/v1/brands/{id}`.
- **Proposed fix:** (a) Exclude `social_credentials` and channel `access_token` fields from `BrandResponse` serialization, or (b) store credentials in a separate encrypted table, or (c) add a `model_serializer` to `BrandResponse` that strips sensitive keys from `brand_guidelines`.

### H6. Race condition in graph token cache (entra.py)
- **File:** `backend/app/auth/entra.py`, lines 73-81
- **Category:** Bug / Reliability
- **Description:** `_graph_token_lock` is created lazily with `asyncio.Lock()`, but this initialization itself is not thread-safe. If two coroutines call `_get_token_lock()` concurrently before the lock is created, two different locks could be created (one overwriting the other). This is a classic TOCTOU race.
- **Proposed fix:** Initialize `_graph_token_lock` at module level or use a `threading.Lock` to protect the creation.

### H7. No pagination on Graph API group members (users.py)
- **File:** `backend/app/api/v1/users.py`, lines 153-184
- **Category:** Bug
- **Description:** `get_security_group_members` fetches members with `$top=999` but does not handle `@odata.nextLink` pagination. If the security group has more than 999 members, the response is silently truncated.
- **Proposed fix:** Implement pagination loop following `@odata.nextLink` until all members are returned.

### H8. `get_graph_users_by_ids` unbounded filter list (entra.py)
- **File:** `backend/app/auth/entra.py`, lines 160-186
- **Category:** Bug / Performance
- **Description:** `get_graph_users_by_ids` builds an OData `$filter` string with `id in (...)` containing all user IDs. The Graph API has a URL length limit (~2048 chars) and an `in` operator limit (~15 values). Passing more than ~15 IDs will cause a 400 error.
- **Proposed fix:** Batch the IDs into chunks of 15 and make multiple Graph API calls, or use the `$batch` endpoint.

### H9. Logo endpoint serves without brand-scoping (brands.py)
- **File:** `backend/app/api/v1/brands.py`, line 310-333
- **Category:** Security
- **Description:** `get_brand_logo` does not require authentication (no `current_user` dependency in the download path), but the endpoint IS authenticated via `db: AsyncSession = Depends(get_db)` -- actually checking: it does NOT have `current_user = Depends(get_current_user)`. This means brand logos are publicly accessible to anyone who knows the brand_id and label.
- **Proposed fix:** Add `current_user: User = Depends(get_current_user)` or accept that logos are intentionally public (and document this decision).

### H10. SSE notification stream never closes DB sessions properly (notifications.py)
- **File:** `backend/app/api/v1/notifications.py`, lines 57-96
- **Category:** Reliability / Performance
- **Description:** The SSE `event_generator` creates a new `async_session_factory()` session every 10 seconds inside an infinite loop. While the `async with` context manager handles each individual session, a malicious or careless client that opens many SSE connections can exhaust the database connection pool (pool_size=20, max_overflow=10).
- **Proposed fix:** Add connection limits per user, add a maximum SSE lifetime, or use a pub/sub mechanism (Valkey/NATS) instead of polling the database.

### H11. Missing `flag_modified` for JSONB update in webhooks.py
- **File:** `backend/app/api/v1/webhooks.py`, lines 95-97
- **Category:** Bug
- **Description:** When updating `content.generation_metadata` in the publish-failed path, the code modifies the dict in-place (`gen_meta["publish_error"] = ...`) and reassigns it. However, SQLAlchemy may not detect the JSONB mutation. This could cause the error to silently not persist.
- **Proposed fix:** Add `from sqlalchemy.orm.attributes import flag_modified; flag_modified(content, "generation_metadata")` after the update.

### H12. `new_status` as query parameter allows arbitrary status injection (content.py)
- **File:** `backend/app/api/v1/content.py`, lines 137-152
- **Category:** Security / Bug
- **Description:** The `transition_content_status` endpoint takes `new_status` as a bare query parameter (`new_status: str`) with no validation against the allowed statuses list. While `_validate_transition` provides some protection, an attacker could pass any string. The `"queued"` reset is always allowed, meaning anyone with editor access can reset any content's status.
- **Proposed fix:** Add validation: `if new_status not in ALL_STATUSES: raise HTTPException(422, ...)` and consider restricting the "queued" reset to managers/admins.

---

## MEDIUM Findings

### M1. `_check_minio` accesses `_client` directly without null check (system.py)
- **File:** `backend/app/api/v1/system.py`, line 72
- **Category:** Bug
- **Description:** `_check_minio` calls `minio_service._client.list_buckets()` directly. If the MinIO client hasn't been initialized yet (`_client is None`), this will raise `AttributeError: 'NoneType' object has no attribute 'list_buckets'` instead of returning "error".
- **Proposed fix:** Use `minio_service.get_client().list_buckets()` which handles lazy initialization.

### M2. Duplicate `/system/services` MinIO check has same issue (system.py)
- **File:** `backend/app/api/v1/system.py`, line 283
- **Category:** Bug
- **Description:** Same as M1, in the `system_services` endpoint.
- **Proposed fix:** Same as M1.

### M3. No rate limiting on AI generation endpoints (intelligence.py)
- **File:** `backend/app/api/v1/intelligence.py`, lines 476-593, 606-660
- **Category:** Security / Performance
- **Description:** The `generate-fields` and `rewrite-field` endpoints make LLM API calls without any rate limiting. A malicious user could rapidly call these endpoints to rack up significant LLM costs.
- **Proposed fix:** Add rate limiting (e.g., `slowapi` or custom middleware) to AI-powered endpoints.

### M4. No rate limiting on web image search (products.py)
- **File:** `backend/app/api/v1/products.py`, lines 215-272, 276-325
- **Category:** Security / Performance
- **Description:** `fetch_product_images` and `batch_fetch_product_images` make external HTTP requests to DuckDuckGo without rate limiting. Could be abused for SSRF-like behavior or to get the server's IP blocked by DuckDuckGo.
- **Proposed fix:** Add rate limiting and limit `batch-fetch-images` to a maximum of ~10 products per request.

### M5. `batch_fetch_product_images` has no limit on product_ids count (products.py)
- **File:** `backend/app/api/v1/products.py`, line 206
- **Category:** Performance
- **Description:** `FetchImagesRequest.product_ids` has no maximum length. A request with thousands of product IDs would make thousands of web requests sequentially.
- **Proposed fix:** Add `max_length=20` or similar to the `product_ids` field.

### M6. `reorder_calendar_items` makes N+1 queries (calendar_service.py)
- **File:** `backend/app/services/calendar_service.py`, lines 96-116
- **Category:** Performance
- **Description:** `reorder_calendar_items` calls `get_calendar_item(db, item_id)` in a loop for each item, resulting in N separate database queries. Then it refreshes each item individually.
- **Proposed fix:** Fetch all items in a single `WHERE id IN (...)` query, then apply updates in a batch.

### M7. Inconsistent error handling in `update_brand` (brands.py)
- **File:** `backend/app/api/v1/brands.py`, lines 99-120
- **Category:** Bug
- **Description:** The `update_brand` endpoint does an additional `UPDATE agent_runs` query after the brand update. If this second query fails, the brand update has already been committed (line 100 inside `brand_service.update_brand`). This creates an inconsistent state where the brand is deactivated but agent runs are not cancelled. Also, the extra `await db.commit()` on line 113 is a separate transaction from the brand update.
- **Proposed fix:** Wrap both operations in a single transaction, or use the same session before committing.

### M8. `settings` parameter shadows `app.config.settings` (settings.py API)
- **File:** `backend/app/api/v1/settings.py`, line 28
- **Category:** Quality / Bug risk
- **Description:** The `update_settings` function parameter is named `settings: dict`, which shadows the imported `settings` from `app.config`. While not causing a bug currently (config settings is not used in this function), it's confusing and error-prone.
- **Proposed fix:** Rename the parameter to `data` or `payload`.

### M9. `engagement_puller` doesn't handle YouTube, TikTok, or X channels
- **File:** `backend/app/scheduler/engagement_puller.py`, lines 88-100
- **Category:** Quality / Bug
- **Description:** The engagement puller only handles Instagram, Facebook, and LinkedIn. All other channels (YouTube, TikTok, X, website_blog, teams) hit `continue` and silently skip engagement tracking. This means analytics dashboards will show zero engagement for content on these platforms.
- **Proposed fix:** Add engagement pulling for YouTube, TikTok, and X when credentials are available, or log a more informative message.

### M10. `search_product_images` SSRF risk via DuckDuckGo redirect (gemini_service.py)
- **File:** `backend/app/services/gemini_service.py`, lines 43-152
- **Category:** Security
- **Description:** `search_product_images` fetches arbitrary URLs found in DuckDuckGo search results, following redirects. A crafted search result could redirect to internal services (e.g., `http://169.254.169.254/` for cloud metadata). The function uses `follow_redirects=True`.
- **Proposed fix:** Validate that fetched URLs are not internal/private IPs before downloading. Add a URL allowlist or blocklist.

### M11. Analytics queries use raw SQL without parameterized LIMIT (analytics.py)
- **File:** `backend/app/api/v1/analytics.py`, line 141
- **Category:** Security (low risk)
- **Description:** `get_top_content` passes `limit` as a bound parameter (`:lim`), which is correct. However, the `days` parameter in `get_engagement_timeseries` (line 75) is also bound. Both are safe. NOTE: These queries are safe from SQL injection since they use bound parameters. However, the `days` parameter has no upper bound validation, allowing unbounded time-range queries.
- **Proposed fix:** Add `Query(le=365)` on the `days` parameter.

### M12. `content_calendar_upcoming` duplicates `upcoming_calendar_items` (content.py vs calendar.py)
- **File:** `backend/app/api/v1/content.py` lines 46-79 and `backend/app/api/v1/calendar.py` lines 30-65
- **Category:** Quality
- **Description:** Two separate endpoints serve essentially the same data (upcoming calendar items). The `/content/calendar/upcoming` endpoint doesn't load brand names, while `/calendar/upcoming` does. This is confusing and maintenance-prone.
- **Proposed fix:** Deprecate or remove the duplicate endpoint in content.py.

### M13. `require_role` decorator may not work correctly with FastAPI dependency injection
- **File:** `backend/app/auth/permissions.py`, lines 23-48
- **Category:** Quality / Bug risk
- **Description:** The `require_role` decorator extracts `current_user` from `kwargs`, but FastAPI routes inject dependencies as keyword arguments. If a route handler uses positional arguments, `kwargs.get("current_user")` could return None even when the user is authenticated. Additionally, this decorator is never used in the codebase -- all role checks use the inline `role_has_access()` function instead.
- **Proposed fix:** Remove the unused `require_role` decorator to reduce dead code, or verify it works with FastAPI's DI system.

### M14. `app_settings` table referenced but never defined as a SQLAlchemy model
- **File:** `backend/app/api/v1/settings.py`, `backend/app/scheduler/__init__.py`, `backend/app/api/v1/intelligence.py`
- **Category:** Quality / Reliability
- **Description:** Multiple files reference an `app_settings` table via raw SQL (`text("SELECT ... FROM app_settings ...")`), but this table has no SQLAlchemy model definition in the models directory. This means: (a) Alembic won't manage it, (b) no type safety, (c) if the table doesn't exist, runtime errors.
- **Proposed fix:** Create an `AppSetting` model in `app/models/` and register it in `__init__.py`.

### M15. `CalendarItemResponse` includes `brand_name` but the model doesn't have this column
- **File:** `backend/app/schemas/calendar_item.py` line 58; `backend/app/services/calendar_service.py` line 15
- **Category:** Quality
- **Description:** `CalendarItemResponse` includes `brand_name: str | None = None` but `CalendarItem` has no `brand_name` column. The service works around this by dynamically setting the attribute (`item.brand_name = ...`). While functional, this is a code smell that could break if ORM validation becomes strict.
- **Proposed fix:** Use a dedicated response DTO that includes brand_name, rather than monkey-patching the ORM object.

### M16. Valkey health check creates a new connection each time (system.py)
- **File:** `backend/app/api/v1/system.py`, lines 44-54, 250-261
- **Category:** Performance
- **Description:** Both `_check_valkey` and the Valkey check in `system_services` create a new `redis.Redis` connection every time, rather than using the connection pool from `ai_model_service._get_valkey_pool()`. This wastes resources and can cause connection leaks.
- **Proposed fix:** Reuse the existing Valkey connection pool from `ai_model_service`.

### M17. `bc_sync.py` uses module-level asyncio.Lock (bc_sync.py)
- **File:** `backend/app/scheduler/bc_sync.py`, line 15
- **Category:** Bug risk
- **Description:** `_sync_lock = asyncio.Lock()` is created at module import time. If the module is imported before any event loop is running, the lock may be bound to a different loop than the one running the scheduler. In Python 3.10+, `asyncio.Lock()` no longer requires an event loop at creation, so this is safe on modern Python. But it's worth noting.
- **Proposed fix:** No action needed if Python >= 3.10. Otherwise, create the lock lazily.

### M18. `discover_models` creates a new session but doesn't handle session errors cleanly
- **File:** `backend/app/services/ai_model_service.py`, lines 227-309
- **Category:** Reliability
- **Description:** `discover_models` modifies existing model objects inside the session, but if `db.commit()` fails (e.g., unique constraint violation on a new model), the entire batch of changes is rolled back without any retry or partial-save logic. Also, `additional_categories` mutation on line 298 modifies `capabilities` dict in-place without `flag_modified`.
- **Proposed fix:** Add `flag_modified(existing_models[model_id], "capabilities")` on line 298. Consider batching commits.

### M19. `set_active_model` manual session management is fragile (ai_model_service.py)
- **File:** `backend/app/services/ai_model_service.py`, lines 370-447
- **Category:** Reliability / Quality
- **Description:** `set_active_model` manually manages `__aenter__` and `__aexit__` on the session factory when no `db` is provided. If an exception occurs between `__aenter__` and the `finally` block, the session may not be properly closed. This is also hard to read and maintain.
- **Proposed fix:** Use `async with async_session_factory() as db:` instead of manual enter/exit.

---

## LOW Findings

### L1. Dead import: `base64` in gemini_service.py
- **File:** `backend/app/services/gemini_service.py`, line 9
- **Category:** Quality
- **Description:** `import base64` is imported but never used.
- **Proposed fix:** Remove the unused import.

### L2. Dead import: `re` in gemini_service.py
- **File:** `backend/app/services/gemini_service.py`, line 11
- **Category:** Quality
- **Description:** `import re` is imported but never used.
- **Proposed fix:** Remove the unused import.

### L3. `ROLE_HIERARCHY` is redundant copy of `ROLES` (permissions.py)
- **File:** `backend/app/auth/permissions.py`, lines 6-11, 13
- **Category:** Quality
- **Description:** `ROLE_HIERARCHY = {role: level for role, level in ROLES.items()}` is just a copy of `ROLES`. Both are identical dicts.
- **Proposed fix:** Remove `ROLE_HIERARCHY` and use `ROLES` directly, or alias it.

### L4. Unused `deliver_policy` parameter in `subscribe` (nats_service.py)
- **File:** `backend/app/services/nats_service.py`, line 76
- **Category:** Quality
- **Description:** The `deliver_policy` parameter is accepted but never used.
- **Proposed fix:** Either pass it to `pull_subscribe()` or remove it.

### L5. No logging when DuckDuckGo image download fails (gemini_service.py)
- **File:** `backend/app/services/gemini_service.py`, line 148
- **Category:** Reliability
- **Description:** The `except Exception: continue` silently swallows all errors when downloading individual images. This makes debugging difficult.
- **Proposed fix:** Add `logger.debug("Failed to download image from %s: %s", url, e)`.

### L6. `_startup_logger` never used beyond the config check block (config.py)
- **File:** `backend/app/config.py`, lines 136
- **Category:** Quality
- **Description:** Minor: the logger and related variables are only used in the production check block. This is fine but slightly unusual.
- **Proposed fix:** No action needed; this is intentional.

### L7. Inconsistent UUID-to-string conversion in raw SQL queries
- **File:** `backend/app/api/v1/brands.py` line 111, `backend/app/api/v1/analytics.py` line 80
- **Category:** Quality
- **Description:** Some raw SQL queries pass UUIDs as `str(brand_id)` (e.g., `{"brand_id": str(brand_id)}`) while the ORM handles UUID objects natively. This inconsistency could cause type mismatch issues with some PostgreSQL drivers.
- **Proposed fix:** Use UUID objects consistently, or ensure `asyncpg` handles both.

### L8. `content_service.list_content` accepts `**kwargs` silently (content_service.py)
- **File:** `backend/app/services/content_service.py`, line 22
- **Category:** Quality
- **Description:** `list_content` accepts `**kwargs` but never uses them. This hides caller errors -- misspelled keyword arguments are silently ignored.
- **Proposed fix:** Remove `**kwargs`.

### L9. No timeout on NATS connection (nats_service.py)
- **File:** `backend/app/services/nats_service.py`, line 31
- **Category:** Reliability
- **Description:** `nats.connect(settings.NATS_URL)` doesn't specify a connection timeout. If NATS is unreachable, this could hang indefinitely during startup.
- **Proposed fix:** Add `connect_timeout=5` parameter.

### L10. `check_due_content` doesn't use `selectinload` for brand relationship
- **File:** `backend/app/scheduler/publish_checker.py`, lines 26-31
- **Category:** Performance
- **Description:** The initial CalendarItem query doesn't eagerly load the brand relationship. The brand is loaded later via `content.brand` (through `selectinload(Content.brand)`), but the calendar item query triggers a separate lazy-load query for each item if any code accesses `calendar_item.brand`.
- **Proposed fix:** Add `.options(selectinload(CalendarItem.brand))` to the initial query if brand is needed.

### L11. Inconsistent use of `created_by` across create endpoints
- **File:** Multiple API files
- **Category:** Quality
- **Description:** Some create endpoints set `created_by` to `current_user.id` (e.g., `create_competitor` in brands.py), while others don't (e.g., `create_campaign`, `create_content`, `create_calendar_item`). The `created_by` foreign key exists on most models but is often left as NULL.
- **Proposed fix:** Consistently set `created_by=current_user.id` on all create operations, or document which entities track the creator.

### L12. Alembic `env.py` hardcodes fallback database URL (alembic/env.py)
- **File:** `backend/alembic/env.py`, line 33-36
- **Category:** Security (low)
- **Description:** The fallback DATABASE_URL uses `markai:markai` as credentials. While this is standard for development, it could be a security concern if the env variable is accidentally unset in production.
- **Proposed fix:** Raise an error if `DATABASE_URL` is not set, rather than falling back to defaults.

### L13. `content/calendar` and `/calendar/` endpoint overlap
- **File:** `backend/app/api/v1/content.py` lines 19-43
- **Category:** Quality
- **Description:** The `content_calendar` endpoint at `/api/v1/content/calendar` partially duplicates the calendar router at `/api/v1/calendar/`. It returns a simpler format without brand names and without service-layer abstraction.
- **Proposed fix:** Deprecate the `/content/calendar` endpoint in favor of `/calendar/`.

---

## Summary by File

| File | Findings | Severity |
|------|----------|----------|
| `services/fabric_service.py` | C1 | CRITICAL |
| `services/minio_service.py` | C2 | CRITICAL |
| `services/qdrant_service.py` | C3 | CRITICAL |
| `auth/entra.py` | H1, H6, H8 | HIGH |
| `api/v1/files.py` | H2 | HIGH |
| `api/v1/products.py` | H3, M4, M5 | HIGH, MEDIUM |
| `api/v1/content.py` | H12, M12 | HIGH, MEDIUM |
| `api/v1/brands.py` | H9, M7 | HIGH, MEDIUM |
| `api/v1/users.py` | H7 | HIGH |
| `services/publish_service.py` | H5 | HIGH |
| `scheduler/engagement_puller.py` | H5, M9 | HIGH, MEDIUM |
| `api/v1/notifications.py` | H10 | HIGH |
| `api/v1/webhooks.py` | H11 | HIGH |
| `api/v1/system.py` | M1, M2, M16 | MEDIUM |
| `api/v1/intelligence.py` | M3 | MEDIUM |
| `services/gemini_service.py` | M10, L1, L2, L5 | MEDIUM, LOW |
| `services/calendar_service.py` | M6, M15 | MEDIUM |
| `api/v1/analytics.py` | M11 | MEDIUM |
| `api/v1/settings.py` | M8, M14 | MEDIUM |
| `auth/permissions.py` | M13, L3 | MEDIUM, LOW |
| `services/ai_model_service.py` | M18, M19 | MEDIUM |
| `scheduler/bc_sync.py` | M17 | MEDIUM |
| `services/content_service.py` | L8 | LOW |
| `services/nats_service.py` | L4, L9 | LOW |
| `scheduler/publish_checker.py` | L10 | LOW |
| `alembic/env.py` | L12 | LOW |
| `config.py` | L6 | LOW |
| Multiple API files | H4, L7, L11 | HIGH, LOW |
| `api/v1/calendar.py` | L13 | LOW |

---

## Recommended Priority Order

1. **Immediate (C1-C3):** Fix blocking I/O -- this affects every request's latency and can cause the entire server to hang under load.
2. **This week (H2, H3, H5, H11):** Security fixes for unauthenticated access, file upload abuse, credential exposure, and data persistence bugs.
3. **Soon (H1, H4, H6, H10, H12):** Auth performance, input validation, race condition, resource exhaustion, and status injection.
4. **Next sprint (M1-M19):** Performance optimizations, dead code removal, and consistency improvements.
5. **Backlog (L1-L13):** Code quality and minor improvements.
