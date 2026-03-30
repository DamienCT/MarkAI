# Phase 6 — Database & Data Layer Audit

**Date:** 2026-03-30
**Scope:** `db/init.sql`, `backend/app/models/`, `backend/app/auth/models.py`, all ORM/raw-SQL queries in `backend/` and `agents/`

---

## 6.1 Schema Audit

### 6.1.1 SQL Tables vs. SQLAlchemy Models — Alignment Matrix

| # | SQL Table | SQLAlchemy Model | Location | Status | Column Mismatches |
|---|-----------|-----------------|----------|--------|-------------------|
| 1 | `users` | `User` | `backend/app/auth/models.py` | MATCH | Model uses `entra_id` mapped to column `entra_object_id` — correct. |
| 2 | `brands` | `Brand` | `backend/app/models/brand.py` | MATCH | All 20 columns align. |
| 3 | `products` | `Product` | `backend/app/models/product.py` | MATCH | All 26 columns align. |
| 4 | `campaigns` | `Campaign` | `backend/app/models/campaign.py` | MATCH | `objective` — SQL has `VARCHAR(100)` with CHECK, model uses `String(255)` without CHECK. Minor width mismatch. |
| 5 | `calendar_items` | `CalendarItem` | `backend/app/models/calendar_item.py` | MATCH | All 22 columns align. |
| 6 | `content` | `Content` | `backend/app/models/content.py` | MATCH | All 21 columns align. |
| 7 | `approvals` | `Approval` | `backend/app/models/approval.py` | MATCH | All 8 columns align. |
| 8 | `prompt_versions` | `PromptVersion` | `backend/app/models/prompt_version.py` | MINOR | `performance_score` — SQL `NUMERIC(5,4)`, model `Numeric` (no precision). `a_b_group` — SQL `VARCHAR(1)`, model `String(255)`. |
| 9 | `agent_runs` | `AgentRun` | `backend/app/models/agent_run.py` | MINOR | `agent_type` — SQL `VARCHAR(100)`, model `String(255)`. `trigger` — SQL `VARCHAR(100)`, model `String(255)`. `cost_usd` — SQL `NUMERIC(10,6)`, model `Numeric` (no precision). |
| 10 | `engagement_metrics` | `EngagementMetric` | `backend/app/models/engagement.py` | MINOR | `channel` — SQL `VARCHAR(50)`, model `String(255)`. `engagement_rate` — SQL `NUMERIC(8,4)`, model `Numeric` (no precision). `sentiment_score` — SQL `NUMERIC(5,4)`, model `Numeric` (no precision). |
| 11 | `competitors` | `Competitor` | `backend/app/models/competitor.py` | MATCH | All 10 columns align. |
| 12 | `adaptations` | `Adaptation` | `backend/app/models/adaptation.py` | MATCH | All 11 columns align. |
| 13 | `scheduled_job_log` | `ScheduledJobLog` | `backend/app/auth/models.py` | MATCH | `job_type` — SQL `VARCHAR(100)`, model `String(255)`. Minor width only. |
| 14 | `audit_log` | `AuditLog` | `backend/app/auth/models.py` | MATCH | `action` — SQL `VARCHAR(100)`, model `String(255)`. `entity_type` — SQL `VARCHAR(100)`, model `String(255)`. Minor width only. |
| 15 | `notifications` | `Notification` | `backend/app/auth/models.py` | MATCH | All 12 columns align. |
| 16 | `ai_model_categories` | `AIModelCategory` | `backend/app/models/ai_model.py` | MATCH | All 4 columns align. |
| 17 | `ai_models` | `AIModel` | `backend/app/models/ai_model.py` | MATCH | All 7 columns align. |
| 18 | `ai_model_selections` | `AIModelSelection` | `backend/app/models/ai_model.py` | MATCH | All 6 columns align. |
| 19 | `app_settings` | **NONE** | — | MISSING MODEL | No SQLAlchemy model; queried exclusively via raw SQL `text()`. Not strictly required but inconsistent. |

**Summary:** 18/19 tables have models. 1 table (`app_settings`) has no model. Column width mismatches are cosmetic (model wider than SQL) and will not cause runtime errors. Numeric precision mismatches could allow storing values that exceed intended precision.

### 6.1.2 Missing CHECK Constraints in ORM Models

The SQL schema defines CHECK constraints on many columns. **None of these are replicated in the SQLAlchemy models:**

| Table | Column | SQL CHECK Constraint | ORM Constraint |
|-------|--------|---------------------|----------------|
| `users` | `role` | `IN ('admin','manager','editor','viewer')` | None |
| `brands` | `status` | `IN ('onboarding','activating','active','inactive')` | None |
| `campaigns` | `objective` | `IN ('awareness','engagement','traffic',...)` | None |
| `campaigns` | `status` | `IN ('draft','active','paused','completed','archived')` | None |
| `calendar_items` | `item_type` | `IN ('post','story','reel',...)` | None |
| `calendar_items` | `channel` | `IN ('instagram','facebook',...)` | None |
| `calendar_items` | `status` | `IN ('queued','working',...)` | None |
| `calendar_items` | `priority` | `BETWEEN 0 AND 5` | None |
| `content` | (none) | — | — |
| `approvals` | `status` | `IN ('pending','approved','rejected','revision_requested')` | None |
| `prompt_versions` | `category` | `IN ('content_generation',...)` | None |
| `prompt_versions` | `a_b_group` | `IN ('A','B')` | None |
| `agent_runs` | `trigger` | `IN ('scheduled','manual','event','webhook','activation')` | None |
| `agent_runs` | `status` | `IN ('pending','running','completed','failed','cancelled')` | None |
| `adaptations` | `target_channel` | Same as calendar_items channel | None |
| `adaptations` | `status` | Same as calendar_items status | None |
| `notifications` | `notification_type` | `IN ('info','success',...)` | None |
| `notifications` | `channel` | `IN ('in_app','email','slack','push')` | None |

**Risk:** Invalid values inserted via ORM will succeed at the Python layer and only fail at DB commit time, producing a cryptic `IntegrityError` instead of a clear validation error. The Pydantic schemas also do **not** validate enum values for `status`, `channel`, `item_type`, etc.

### 6.1.3 Missing UNIQUE Constraints in ORM

| Table | SQL Constraint | ORM |
|-------|---------------|-----|
| `prompt_versions` | `UNIQUE(slug, version)` | Not declared — relies on DB enforcement only. |
| `ai_models` | `UNIQUE(provider, model_id)` | Not declared in model. |
| `ai_model_selections` | `UNIQUE(category_slug, model_id)` | Not declared in model. |

### 6.1.4 Indexes

The SQL schema is well-indexed. All foreign keys have explicit indexes. Commonly queried columns (`status`, `channel`, `brand_id`, etc.) are covered. The GIN index on `products.tags` is present for array searches.

**No missing critical indexes identified.**

### 6.1.5 Timestamps

| Table | `created_at` | `updated_at` | Notes |
|-------|-------------|-------------|-------|
| `users` | Yes | Yes | |
| `brands` | Yes | Yes | |
| `products` | Yes | Yes | |
| `campaigns` | Yes | Yes | |
| `calendar_items` | Yes | Yes | |
| `content` | Yes | Yes | |
| `approvals` | Yes | Yes | |
| `prompt_versions` | Yes | Yes | |
| `agent_runs` | Yes | **No** | Only has `created_at`. No `updated_at`. Acceptable for an append-mostly log table. |
| `engagement_metrics` | Yes | **No** | Only has `created_at` + `fetched_at`. Append-only, acceptable. |
| `competitors` | Yes | Yes | |
| `adaptations` | Yes | Yes | |
| `scheduled_job_log` | Yes | **No** | Append-only log, acceptable. |
| `audit_log` | Yes | **No** | Append-only log, acceptable. |
| `notifications` | Yes | **No** | Append-only, acceptable. |
| `ai_model_categories` | Yes | **No** | Reference data, acceptable. |
| `ai_models` | **No** | **No** | Only has `discovered_at`. No `created_at` or `updated_at`. |
| `ai_model_selections` | **No** | **No** | Only has `set_at`. No `created_at` or `updated_at`. |
| `app_settings` | **No** | Yes (`updated_at`) | No `created_at`. |

### 6.1.6 Alembic / Migrations

**No `alembic/` directory exists.** There are zero migration files. The schema is managed entirely via `db/init.sql`. This means:
- No migration history or rollback capability
- Schema changes must be applied manually or by re-running init.sql
- No way to track incremental schema evolution

**Severity: MEDIUM** — Acceptable for early-stage but will become a liability as the schema evolves.

---

## 6.2 ORM & Query Audit

### 6.2.1 SQL Injection Analysis

| Location | Query Style | Parameterized? | Verdict |
|----------|------------|----------------|---------|
| `backend/app/services/*.py` | SQLAlchemy ORM (`select()`, `where()`) | Yes (inherent) | SAFE |
| `backend/app/api/v1/dashboard.py` | `text()` with no user params | N/A | SAFE |
| `backend/app/api/v1/analytics.py` | `text()` with `:named` params | Yes | SAFE |
| `backend/app/api/v1/settings.py` | `text()` with `:named` params | Yes | SAFE |
| `agents/shared/tools/database.py` | `text()` with `:named` params everywhere | Yes | SAFE |
| `backend/app/services/fabric_service.py` | `?` parameterized + table name whitelist | Yes | SAFE |
| `agents/shared/tools/database.py:517` | **`execute_query(query, params)`** — accepts arbitrary SQL | Depends on caller | **RISK** |
| `agents/shared/tools/database.py:523` | **`execute_update(query, params)`** — accepts arbitrary SQL | Depends on caller | **RISK** |

**DB-6.2.1-CRITICAL: `execute_query` and `execute_update` are generic raw-SQL execution functions.** Any caller can pass arbitrary SQL. While current callers use parameterized queries, the function signature provides no guardrails. A single careless call (e.g., f-string interpolation by an agent workflow node) would enable SQL injection.

### 6.2.2 N+1 Query Patterns

| Location | Pattern | Severity |
|----------|---------|----------|
| `calendar_service.py` | Uses `selectinload(CalendarItem.brand)` — properly eager-loaded | OK |
| `publish_checker.py` | Loops over `due_items`, queries `Content` per item inside loop | **N+1** — LOW (typically small N) |
| `engagement_puller.py` | Loops over `calendar_items`, queries `Content` per item inside loop | **N+1** — MEDIUM (could be 100+ items) |
| `bc_sync.py` | Loops over brands, then loops over stock items calling `upsert_from_bc` per item | **N+1** — MEDIUM (could be 1000+ products) |
| `agents/shared/tools/database.py:store_competitors` | Loop with individual INSERT per competitor | **N+1** — LOW |
| `agents/shared/tools/database.py:store_calendar_items` | Loop with individual INSERT per item | **N+1** — MEDIUM (could be 50+ items per planning cycle) |
| `agents/shared/tools/database.py:store_adaptations` | Loop with individual INSERT per adaptation | **N+1** — LOW |
| `prompt_service.py:activate_prompt` | Loads all other versions then updates in loop | **N+1** — LOW (few versions per slug) |

**DB-6.2.2-MEDIUM:** The `bc_sync.py` and `engagement_puller.py` N+1 patterns could become performance issues at scale. Batch operations (`executemany` or bulk inserts) should replace per-row loops.

### 6.2.3 Transaction Boundaries

| Location | Issue | Severity |
|----------|-------|----------|
| `agents/shared/tools/database.py` | Each function opens its own `async with async_session_factory() as session`. No cross-function transaction support. | LOW — agents are fire-and-forget, not ACID-critical |
| `backend/app/deps.py:get_db` | Yields a session per request. Session is not wrapped in explicit `begin()`. Relies on SQLAlchemy autobegin. | OK — standard FastAPI pattern |
| `publish_checker.py` | Commits `status = "publishing"` separately from the dispatch result. If dispatch fails after commit, the item stays in "publishing" state forever (but is then set to "failed" in the except block). | OK — handled in except |
| `agents/shared/tools/database.py:store_content` | Two operations (UPDATE old content + INSERT new) share a session and single commit. | OK — atomic |

### 6.2.4 Connection Pool / Leak Analysis

| Component | Pool Config | Issue |
|-----------|------------|-------|
| Backend (`base.py`) | `pool_size=20, max_overflow=10` | OK for a single backend instance |
| Agents (`database.py`) | `pool_size=10, max_overflow=20` | OK |
| Backend `get_db` | `async with` + `finally: session.close()` | SAFE — no leak |
| Agents all functions | `async with async_session_factory() as session` | SAFE — context manager closes |
| `ai_model_service.py:set_active_model` | Manual `__aenter__`/`__aexit__` on session | **FRAGILE** — if an exception occurs between `__aenter__` and the `try/finally`, the session leaks. Should use `async with`. |

**DB-6.2.4-LOW:** The manual session management in `set_active_model` is fragile but unlikely to leak in practice because the `try/finally` covers the critical path.

### 6.2.5 Missing Error Handling on DB Operations

| Location | Issue |
|----------|-------|
| `agents/shared/tools/database.py:upsert_product` | `ON CONFLICT (brand_id, bc_item_no)` — but there is **no unique index or constraint** on `(brand_id, bc_item_no)` in the SQL schema. This `ON CONFLICT` clause will cause a runtime error. |
| `backend/app/api/v1/analytics.py` | Multiple raw SQL queries with no try/except. A DB error will propagate as 500. |
| `backend/app/api/v1/dashboard.py` | Same — raw SQL with no error handling. |
| `agents/shared/tools/database.py:get_performance_data` | References `em.measured_at` — **this column does not exist**. The engagement_metrics table has `fetched_at`, not `measured_at`. This query will fail at runtime. |
| `agents/shared/tools/database.py:store_adaptations` | Evaluation-node branch inserts `brand_id`, `tier`, `confidence`, `data` columns — **none of these exist** on the `adaptations` table. This will fail at runtime. |

---

## 6.3 Data Integrity

### 6.3.1 DB-Level Constraints for Business Rules

| Rule | DB Constraint? | Notes |
|------|---------------|-------|
| Brand status transitions | **No** | Only CHECK for valid values, no transition logic |
| Calendar item status transitions | **No** | Enforced only in Python (`content_service.py:VALID_TRANSITIONS`) |
| Approval can only be resolved once | **No** | Enforced only in Python (`approval_service.py`) |
| Content version uniqueness per calendar item | **No** | No unique constraint on `(calendar_item_id, version)` |
| One current content per calendar item | **No** | No partial unique index on `(calendar_item_id) WHERE is_current = true` |
| Product BC item uniqueness per brand | **No** | **No unique constraint on `(brand_id, bc_item_no)`** — the `upsert_product` ON CONFLICT clause in agents relies on this but it doesn't exist |
| Prompt version uniqueness | Yes | `UNIQUE(slug, version)` in SQL |
| AI model uniqueness | Yes | `UNIQUE(provider, model_id)` in SQL |

### 6.3.2 Input Validation at API Boundaries

| Endpoint Area | Pydantic Schema? | Validates Enums? | Validates Lengths? |
|--------------|-----------------|-------------------|-------------------|
| Brands CRUD | Yes (`BrandCreate`, `BrandUpdate`) | **No** — `status` accepts any string | **No** — no `max_length` on strings |
| Calendar Items | Yes (`CalendarItemCreate`) | **No** — `item_type`, `channel`, `status` accept any string | **No** |
| Content | Yes (`ContentCreate`) | **No** | **No** |
| Approvals | Yes (`ApprovalCreate`) | **No** | **No** |
| Campaigns | Yes (`CampaignCreate`) | **No** | **No** |
| Settings PUT | **No** — accepts raw `dict` | N/A | N/A |
| Agent workflows (NATS) | **No Pydantic validation** — raw dicts from NATS messages | N/A | N/A |

**DB-6.3.2-MEDIUM:** Pydantic schemas exist but do not validate enum/CHECK values or string lengths. Invalid values will pass the API layer and only fail at DB commit time with an `IntegrityError`.

### 6.3.3 Data Consistency Between Related Tables

| Issue | Severity |
|-------|----------|
| `content.ai_prompt_version` is a bare UUID with **no FK** to `prompt_versions.id` in the ORM model (SQL schema also has no FK). Orphaned references possible. | LOW |
| `calendar_items.product_ids` is a UUID array, not a FK relationship. No referential integrity — deleted products leave stale IDs. | MEDIUM |
| `User` and `Notification` models are in `backend/app/auth/models.py`, separate from the main `backend/app/models/` directory. `ScheduledJobLog` and `AuditLog` are also there. These are **not exported** from `backend/app/models/__init__.py`. | LOW — works because imports reference `app.auth.models` directly |
| Two separate database connection pools exist: backend (`base.py`, pool_size=20) and agents (`database.py`, pool_size=10). If both run in the same process, total connections = 30 + overflow. | LOW — they run in separate containers |

---

## Summary of Findings

### CRITICAL

| ID | Finding | File(s) |
|----|---------|---------|
| DB-C1 | `get_performance_data` references non-existent column `em.measured_at` (should be `fetched_at`) — query will crash at runtime | `agents/shared/tools/database.py:429-430` |
| DB-C2 | `store_adaptations` evaluation-node branch inserts into non-existent columns (`brand_id`, `tier`, `confidence`, `data`) on the `adaptations` table — will crash at runtime | `agents/shared/tools/database.py:452-468` |
| DB-C3 | `upsert_product` uses `ON CONFLICT (brand_id, bc_item_no)` but no unique constraint exists on those columns — will crash at runtime | `agents/shared/tools/database.py:310-323` |
| DB-C4 | `execute_query` / `execute_update` accept arbitrary SQL strings with no safeguards — SQL injection vector if any caller uses string interpolation | `agents/shared/tools/database.py:517-531` |

### HIGH

| ID | Finding | File(s) |
|----|---------|---------|
| DB-H1 | No Alembic migrations — schema changes cannot be tracked, versioned, or rolled back | `alembic/` (missing) |
| DB-H2 | No Pydantic enum validation on any schema — invalid `status`, `channel`, `item_type` values pass API validation | `backend/app/schemas/*.py` |
| DB-H3 | No unique constraint on `(brand_id, bc_item_no)` in products table — BC sync can create duplicates | `db/init.sql` products table |

### MEDIUM

| ID | Finding | File(s) |
|----|---------|---------|
| DB-M1 | N+1 query pattern in `bc_sync.py` — individual `upsert_from_bc` per product in loop (potentially 1000+ items) | `backend/app/scheduler/bc_sync.py:115-148` |
| DB-M2 | N+1 query pattern in `engagement_puller.py` — individual content query per calendar item | `backend/app/scheduler/engagement_puller.py:67-78` |
| DB-M3 | N+1 in agent `store_calendar_items` — individual INSERT per calendar item in loop | `agents/shared/tools/database.py:334-412` |
| DB-M4 | Numeric precision not specified in ORM models (`Numeric` without `(p,s)`) for `cost_usd`, `engagement_rate`, `sentiment_score`, `performance_score` — allows values exceeding intended range | Multiple model files |
| DB-M5 | String width mismatches — several ORM models use `String(255)` where SQL uses `VARCHAR(100)` or `VARCHAR(50)`. Not a runtime issue but indicates drift. | `agent_run.py`, `engagement.py`, `prompt_version.py`, `scheduled_job_log.py`, `audit_log.py` |
| DB-M6 | `calendar_items.product_ids` UUID array has no referential integrity — deleted products leave dangling references | `db/init.sql`, `calendar_item.py` |
| DB-M7 | No partial unique index to enforce "one current content per calendar item" — business rule enforced only in application code | `db/init.sql` content table |

### LOW

| ID | Finding | File(s) |
|----|---------|---------|
| DB-L1 | `app_settings` has no SQLAlchemy model — queried via raw SQL only | All settings queries |
| DB-L2 | `ai_model_service.py:set_active_model` uses manual `__aenter__`/`__aexit__` instead of `async with` | `backend/app/services/ai_model_service.py:377-447` |
| DB-L3 | `content.ai_prompt_version` has no FK constraint — orphaned references possible | `db/init.sql`, `content.py` |
| DB-L4 | CHECK constraints not mirrored in ORM models — invalid values only caught at DB commit | All model files |
| DB-L5 | Composite unique constraints (`prompt_versions(slug,version)`, `ai_models(provider,model_id)`, `ai_model_selections(category_slug,model_id)`) not declared in ORM — relies on DB enforcement | Model files |

---

## Recommended Fixes (Priority Order)

1. **DB-C1/C2/C3:** Fix the three broken queries immediately — they will crash at runtime.
2. **DB-C4:** Add input validation or remove the generic `execute_query`/`execute_update` functions; replace with purpose-built parameterized functions.
3. **DB-H3:** Add `UNIQUE(brand_id, bc_item_no)` constraint to `products` table (or a partial unique index where `bc_item_no IS NOT NULL`).
4. **DB-H2:** Add `Literal` type annotations or Pydantic validators for all enum fields in schemas.
5. **DB-H1:** Initialize Alembic, generate an initial migration from the current schema, and use migrations going forward.
6. **DB-M1/M2/M3:** Replace per-row loops with batch operations (`executemany`, `bulk_save_objects`, or `INSERT ... SELECT`).
7. **DB-M4/M5:** Align ORM column types (precision, widths) with SQL schema.
8. **DB-M7:** Add partial unique index: `CREATE UNIQUE INDEX ON content (calendar_item_id) WHERE is_current = true`.
