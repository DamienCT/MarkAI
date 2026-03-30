# MARKAI Performance & Optimization Audit (Phase 5)

**Date:** 2026-03-30
**Auditor:** Claude Opus 4.6

---

## 5.1 Backend Performance

### 5.1.1 N+1 Queries

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B1 | `api/v1/analytics.py:14-55` `get_analytics_summary()` | **8 sequential DB queries** to fetch summary stats. Each metric (impressions, likes, comments, shares, reach, clicks, avg_rate, published count) is a separate `SELECT` query. | **HIGH** | Combine into a single query: `SELECT COALESCE(SUM(impressions),0), COALESCE(SUM(likes),0), ... FROM engagement_metrics`. One query for engagement_metrics aggregates, one for calendar_items count. Reduces 8 round trips to 2. |
| B2 | `api/v1/dashboard.py:11-48` `dashboard_stats()` | **6 sequential COUNT queries** for brands, content, pending approvals, scheduled posts, published this week, active workflows. Each is a separate `SELECT count(*)`. | **HIGH** | Combine into a single query using conditional aggregation: `SELECT COUNT(*) FILTER (WHERE ...) FROM ...` or a UNION ALL of counts. Alternatively use a single raw SQL with subqueries. Reduces 6 round trips to 1. |
| B3 | `services/ai_model_service.py:450-486` `list_categories()` | Fetches all categories, then **loops to query active model for each category** individually. For N categories, this executes N+1 queries. | **MEDIUM** | Use a single LEFT JOIN query: `SELECT cat.*, m.* FROM ai_model_categories cat LEFT JOIN ai_model_selections sel ON ... LEFT JOIN ai_models m ON ...`. Reduces N+1 to 1 query. |
| B4 | `api/v1/content.py:19-43` `content_calendar()` | Fetches CalendarItems but does **not eager-load the brand relationship**. If any serialization or downstream code touches `item.brand`, it triggers lazy loads. | **LOW** | Add `.options(selectinload(CalendarItem.brand))` to the query like `calendar_service.list_calendar_items()` does. The calendar endpoint in `content.py` is a duplicate of the one in `calendar.py` and should be consolidated. |
| B5 | `services/calendar_service.py:96-116` `reorder_calendar_items()` | Loops through items calling `get_calendar_item()` individually for each item in the reorder list. Each call runs a SELECT with selectinload. | **MEDIUM** | Fetch all items in a single `WHERE id IN (...)` query, then update them in a batch. Reduces N queries to 1. |
| B6 | `api/v1/products.py:275-325` `batch_fetch_product_images()` | Loops through product IDs **sequentially**, calling `get_product()` + `search_product_images()` + MinIO uploads + DB commit for each. | **MEDIUM** | Use `asyncio.gather()` or `asyncio.Semaphore`-guarded concurrency to process multiple products in parallel (with a reasonable concurrency limit like 3-5). Each product involves network I/O (web scraping + MinIO upload) that blocks the loop. |

### 5.1.2 Unbounded Fetches / Missing Pagination

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B7 | `api/v1/analytics.py:14-55` `get_analytics_summary()` | Full-table aggregation over `engagement_metrics` with **no brand_id filter, no date range**. Scans the entire table every call. | **HIGH** | Add required or default date range filter (e.g., last 90 days). Consider materializing summary stats in a cache or materialized view. |
| B8 | `api/v1/analytics.py:96-115` `get_posting_heatmap()` | Scans all `calendar_items` with status `published` or `scheduled`. **No date range, no brand filter, no limit.** | **MEDIUM** | Add default date range (last 6-12 months) and optional brand_id filter. |
| B9 | `api/v1/brands.py:391-408` `list_brand_competitors()` | Fetches **all** competitors for a brand with no limit. While unlikely to be huge, no pagination guard. | **LOW** | Add `.limit(100)` as a safety guard. |
| B10 | `api/v1/intelligence.py:74-169` `list_intelligence_reports()` | Returns agent runs with **full `output_payload` JSONB** which can be very large (strategy documents, multi-page markdown). This is serialized and sent over the wire for list views. | **HIGH** | Exclude `output_payload` from the list response (or truncate it). Only return the full payload in the detail endpoint `get_report()`. Use deferred column loading or explicit column selection. |
| B11 | Default `limit=100` on most list endpoints | Many endpoints default to `limit=100` (brands, content, products, campaigns, prompts, approvals). While paginated, there is no **maximum limit cap**. A client could pass `limit=999999`. | **MEDIUM** | Add `limit = min(limit, 200)` or similar cap in each endpoint to prevent accidental or malicious unbounded fetches. |

### 5.1.3 Connection Pooling

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B12 | `models/base.py:10-15` | SQLAlchemy async engine configured with `pool_size=20, max_overflow=10`. This is **reasonable** for a single-server deployment. | **OK** | No change needed. Consider tuning based on actual connection count under load. |
| B13 | `services/minio_service.py` | MinIO client is a **singleton** created lazily. The `Minio` SDK uses urllib3 connection pooling internally. | **OK** | No issue. |
| B14 | `services/fabric_service.py:64-76` `_get_connection()` | Creates a **new pyodbc connection for every query** to Fabric SQL. No connection pooling. Each call to `execute_sql()` opens and closes a connection. | **HIGH** | Use a connection pool (e.g., via `pyodbc` pool or `aioodbc`). At minimum, cache the connection with a TTL matching the token lifetime. The current pattern adds significant latency for BC sync operations. |
| B15 | `api/v1/system.py:249-261` Valkey health check | Creates a **new Redis connection** for each health check call (and each Valkey check in `_check_valkey()`). No connection reuse. | **MEDIUM** | Use a shared Valkey connection pool (the `ai_model_service.py` already has `_get_valkey_pool()` -- reuse it as a shared module). |
| B16 | `services/ai_model_service.py:98-117` | Properly implements a module-level Valkey connection pool. Good pattern. | **OK** | No change needed. |

### 5.1.4 Caching Strategy

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B17 | `api/v1/analytics.py` | **No caching** on any analytics endpoints. Summary stats, timeseries, and heatmap data are computed from scratch on every request via full-table scans. | **HIGH** | Cache analytics responses in Valkey with 5-15 minute TTL. Analytics data changes infrequently (only when engagement metrics are pulled, which happens every 6 hours). |
| B18 | `api/v1/dashboard.py` | **No caching** on dashboard stats. 6 COUNT queries on every page load. | **HIGH** | Cache dashboard stats in Valkey with 2-5 minute TTL. Invalidate on relevant write operations. |
| B19 | `services/ai_model_service.py` | Good caching with Valkey + in-memory fallback for active model selections (5 min TTL). | **OK** | Good pattern. |
| B20 | `api/v1/files.py:48-52` | File proxy sets `Cache-Control: public, max-age=3600` (1 hour). | **OK** | Good. Could increase to 24h or longer for immutable assets (product images, logos). |
| B21 | Brand logo serving `api/v1/brands.py:310-333` | Logo endpoint has **no Cache-Control header**. Every logo request hits MinIO. | **MEDIUM** | Add `Cache-Control: public, max-age=86400` header. Logos rarely change. |

### 5.1.5 Blocking Sync Calls in Async Context

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B22 | `services/fabric_service.py:79-100` `execute_sql()` | `pyodbc.connect()` and `cursor.execute()` are **blocking synchronous calls** inside an `async def`. This blocks the entire event loop during Fabric SQL queries (which involve network I/O to Azure). | **CRITICAL** | Wrap in `asyncio.to_thread()` or use `aioodbc` (async ODBC driver). Current implementation blocks the FastAPI event loop during every BC sync and Fabric query, stalling all other requests. |
| B23 | `services/minio_service.py` | All MinIO operations (`put_object`, `get_object`, `remove_object`, `list_buckets`) are **synchronous blocking calls** via the `minio` SDK. These are called from async endpoints. | **HIGH** | Wrap MinIO calls in `asyncio.to_thread()` or use an async MinIO client. Currently, every file upload/download/logo serve blocks the event loop. |
| B24 | `services/qdrant_service.py` | All Qdrant operations (`upsert`, `search`, `delete`, `get_collections`) are **synchronous blocking calls**. | **MEDIUM** | Wrap in `asyncio.to_thread()` or use `qdrant_client.AsyncQdrantClient`. Currently lower impact since Qdrant is not heavily used in hot paths. |
| B25 | `main.py:49` `minio_service.ensure_bucket()` | Synchronous MinIO call during startup lifespan. | **LOW** | Acceptable during startup. Wrap in `asyncio.to_thread()` for cleanliness. |

### 5.1.6 Middleware Ordering

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| B26 | `main.py:71-77` | Only one middleware: CORSMiddleware. Ordering is correct. | **OK** | No issue. |
| B27 | No rate limiting middleware | No request rate limiting on any endpoints. The AI field generation endpoints (`/intelligence/generate-fields`, `/intelligence/rewrite-field`) call external LLMs and are expensive. | **MEDIUM** | Add rate limiting middleware (e.g., `slowapi`) for expensive endpoints, especially AI generation and file upload endpoints. |
| B28 | No request size limiting | No middleware to limit request body size. File uploads check 5MB in code, but the full body is already read into memory by then. | **LOW** | Add body size limit middleware or use `starlette.middleware.trustedhost` + nginx `client_max_body_size`. |

---

## 5.2 Frontend Performance

### 5.2.1 Unnecessary Re-renders / Missing Memoization

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| F1 | `components/content/KanbanBoard.tsx:166-196` | `items.filter()` is called **inline inside JSX** for every column on every render. With 9 columns, this runs 9 filter passes over the full items array on every render. | **MEDIUM** | Memoize column items with `useMemo()`: `const columnMap = useMemo(() => { const map = {}; items.forEach(item => { if (!map[item.status]) map[item.status] = []; map[item.status].push(item); }); return map; }, [items])`. Single pass instead of 9. |
| F2 | `components/content/CalendarView.tsx:99-107` `getItemsForDay()` | Called **for every day cell** in the calendar grid. With ~30-31 days, this runs 30+ filter passes over all items. Each pass also calls `parseISO()` and `isSameDay()`. | **MEDIUM** | Pre-compute a date-to-items map with `useMemo()`. Group items by date string once, then O(1) lookup per day. |
| F3 | `components/content/KanbanBoard.tsx:62-79` `SortableItem` | Not memoized with `React.memo()`. Re-renders on every parent render even when the item hasn't changed. | **LOW** | Wrap with `React.memo()`. |
| F4 | `components/content/KanbanBoard.tsx:81-116` `KanbanCard` | Not memoized. Re-renders on every drag event. | **LOW** | Wrap with `React.memo()`. |
| F5 | `app/page.tsx` (Dashboard) | Three API calls on mount with `Promise.allSettled()`. Good pattern. But there is **no AbortController cleanup** -- if the component unmounts before requests complete, state updates on unmounted component occur. | **LOW** | Add AbortController in useEffect cleanup, similar to `content/page.tsx`. |
| F6 | `components/brand/BrandOnboarding.tsx:49-68` | Two separate `useEffect` hooks each make API calls on mount (`products` and `competitors`). These could be combined into one `Promise.allSettled()`. | **LOW** | Combine into a single useEffect with `Promise.allSettled()`. |

### 5.2.2 Bundle Size Concerns

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| F7 | `recharts` (package.json) | `recharts` is ~300KB gzipped and loaded on the main bundle. Only used on analytics and dashboard pages. | **MEDIUM** | Use `next/dynamic` to dynamically import `EngagementChart`, `PerformanceGrid`, `PostingHeatmap` components. This keeps recharts out of the initial page load bundle. |
| F8 | `@dnd-kit/core` + `@dnd-kit/sortable` | DnD libraries loaded for the content page Kanban board. Not needed on other pages. | **MEDIUM** | Use `next/dynamic` to dynamically import `KanbanBoard`. The `"use client"` directive already ensures client rendering, but the code is still in the main JS bundle. |
| F9 | `date-fns` (package.json) | `date-fns` v4 is tree-shakeable. Individual function imports (`format`, `parseISO`, etc.) are used correctly. | **OK** | No issue. Good tree-shaking practice. |
| F10 | `react-markdown` | Only used on intelligence report detail page. Loaded in main bundle. | **LOW** | Use `next/dynamic` for the report detail page component. |
| F11 | `lucide-react` | Individual icon imports used throughout. Tree-shakeable. | **OK** | Good pattern. |

### 5.2.3 Image Optimization

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| F12 | `next.config.ts:5-13` | `images.unoptimized: true` disables Next.js image optimization entirely. All images served as-is without resizing, format conversion, or lazy loading benefits. | **HIGH** | Remove `unoptimized: true`. Configure `remotePatterns` for the API domain. Use `<Image>` component from `next/image` for product images and logos. This enables automatic WebP conversion, responsive sizing, and lazy loading. |
| F13 | Brand logos / product images | Currently served via `<img>` tags or CSS backgrounds using raw MinIO proxy URLs. No responsive sizing or format optimization. | **MEDIUM** | Use `next/image` `<Image>` component with `loader` prop pointing to the API proxy. Enables automatic optimization. |

### 5.2.4 React-Specific Patterns

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| F14 | `app/content/page.tsx:77-93` | The `useEffect` subscribes to `brand-changed` custom event. Cleanup is correct (removes listener + aborts). Good pattern. | **OK** | No issue. |
| F15 | `app/content/page.tsx:96-129` | Effect to update available channels when `formBrandId` or `brands` changes. Has both `formBrandId` and `brands` in deps array. OK, but `brands` changing triggers re-evaluation even when `formBrandId` hasn't changed. | **LOW** | Minor optimization: only re-evaluate if `formBrandId` is set. |
| F16 | `components/analytics/EngagementChart.tsx:30-34` | `formattedData` is computed on every render without memoization. For large datasets, `parseISO()` on every data point adds up. | **LOW** | Wrap in `useMemo(() => ..., [data])`. |
| F17 | Various components | All list renders use proper `key` props (item.id). | **OK** | Good pattern. |
| F18 | `components/content/CalendarView.tsx:241-316` | Expanded day overlay is rendered with a simple `div` overlay. Not using a portal. Works but could interfere with parent overflow/z-index. | **LOW** | Consider using a `Dialog` component or React portal for the overlay. Functional but not ideal. |
| F19 | Notification SSE stream `api/v1/notifications.py:57-96` | The SSE endpoint polls DB every 10 seconds per connected user. With many concurrent users, this creates N DB queries every 10 seconds. | **MEDIUM** | Consider push-based notifications via NATS subscription or WebSocket. The polling approach does not scale well with user count. |

---

## 5.3 Database Performance

### 5.3.1 Index Analysis

| # | Table | Missing Index | Impact | Fix |
|---|-------|---------------|--------|-----|
| D1 | `engagement_metrics` | Missing composite index on `(brand_id, fetched_at)` for brand-filtered time-range queries used in `get_engagement_timeseries()` and `get_brand_metrics()`. | **HIGH** | `CREATE INDEX idx_engagement_metrics_brand_fetched ON engagement_metrics (brand_id, fetched_at DESC);` |
| D2 | `engagement_metrics` | Missing composite index on `(calendar_item_id, content_id)` for JOIN queries in `get_top_content()` and `get_brand_metrics()`. | **MEDIUM** | `CREATE INDEX idx_engagement_metrics_cal_content ON engagement_metrics (calendar_item_id, content_id);` |
| D3 | `calendar_items` | Missing composite index on `(status, published_at)` for the dashboard query `WHERE status = 'published' AND published_at >= now() - interval '7 days'`. | **MEDIUM** | `CREATE INDEX idx_calendar_items_status_published ON calendar_items (status, published_at DESC) WHERE status = 'published';` (partial index) |
| D4 | `agent_runs` | Missing composite index on `(brand_id, agent_type, created_at)` for `get_research_results()` which filters by both brand_id and agent_type. | **MEDIUM** | `CREATE INDEX idx_agent_runs_brand_type_created ON agent_runs (brand_id, agent_type, created_at DESC);` |
| D5 | `agent_runs` | Missing composite index on `(agent_type, status, completed_at)` for `get_trending_topics()` which filters by agent_type + status and orders by completed_at. | **LOW** | `CREATE INDEX idx_agent_runs_type_status_completed ON agent_runs (agent_type, status, completed_at DESC);` |
| D6 | `content` | Missing composite index on `(calendar_item_id, is_current)` for content lookups by calendar item. | **LOW** | `CREATE INDEX idx_content_cal_item_current ON content (calendar_item_id) WHERE is_current = TRUE;` (partial index) |
| D7 | `adaptations` | Missing index on `(source_content_id, status)` for filtered adaptation lookups. | **LOW** | `CREATE INDEX idx_adaptations_source_status ON adaptations (source_content_id, status);` |

### 5.3.2 Existing Indexes -- Good Coverage

The schema has good index coverage in several areas:
- Foreign key indexes on all FK columns (brands.created_by, products.brand_id, etc.)
- Status columns indexed on calendar_items, agent_runs, approvals
- Composite index `idx_calendar_items_brand_scheduled` on (brand_id, scheduled_at DESC) -- good for calendar queries
- Partial index `idx_notifications_user_unread` on (user_id, is_read) WHERE is_read = FALSE -- excellent for unread notification queries
- GIN index on `products.tags` for array containment queries
- Descending indexes on timestamp columns used for ORDER BY DESC

### 5.3.3 Pagination Implementation

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| D8 | All list endpoints | Use OFFSET/LIMIT pagination. This is **correct but slow for deep pages** (OFFSET 10000 still scans 10000 rows). | **LOW** | Acceptable for current scale. If tables grow beyond ~100K rows, consider keyset (cursor) pagination using `WHERE created_at < :last_seen ORDER BY created_at DESC LIMIT :n`. |
| D9 | `api/v1/approvals.py:15-39` `list_approvals()` | Returns both `items` and `total` count. The count query runs a separate full scan. | **LOW** | Cache the total count or use PostgreSQL `count(*) OVER()` window function in a single query. |
| D10 | Most list endpoints | Do not return a `total` count. This means the frontend cannot display "page X of Y" or know if there are more pages. | **LOW** | Consider adding total count to responses (with caching), or use "has_more" pattern: fetch limit+1 items, return limit items, set `has_more = true` if limit+1 items were found. |

### 5.3.4 Transaction Management

| # | Location | Issue | Impact | Fix |
|---|----------|-------|--------|-----|
| D11 | `deps.py:19-25` `get_db()` | Each request gets its own session. Session is closed in `finally` block. SQLAlchemy async session with `expire_on_commit=False`. | **OK** | Good pattern. |
| D12 | `api/v1/brands.py:99-120` `update_brand()` | Two separate commits in the same endpoint: first for brand update, second for cancelling agent_runs. If the second commit fails, the brand is already updated but agents are not cancelled. | **MEDIUM** | Combine into a single transaction. Move the agent_runs cancellation before the first commit, or use a single commit after both operations. |
| D13 | `services/product_service.py:71-91` `upsert_from_bc()` | Commits after **every single product** upsert during BC sync. For 500 products, this is 500 commits. | **HIGH** | Batch commits -- collect all upserts, then commit once (or every 50-100 items). The caller `sync_brand_products()` in `products.py` loops through stock_rows calling `upsert_from_bc()` one at a time. |
| D14 | `api/v1/products.py:275-325` `batch_fetch_product_images()` | Commits after **each product** in the loop. | **MEDIUM** | Commit once after all products are processed, or batch commits every N products. |
| D15 | `services/notification_service.py:89-100` `notify_failure()` | Creates notifications for each admin in a loop, but only commits once after the loop completes. | **OK** | Good pattern -- batches writes before commit. |

---

## Summary: Priority Rankings

### CRITICAL (Fix immediately)
1. **B22** -- Blocking `pyodbc` calls in async context (fabric_service.py) -- stalls entire event loop

### HIGH (Fix in next sprint)
2. **B1** -- 8 sequential DB queries in analytics summary
3. **B2** -- 6 sequential DB queries in dashboard stats
4. **B7** -- Unbounded full-table scan in analytics summary
5. **B10** -- Full JSONB output_payload returned in list endpoints
6. **B14** -- No connection pooling for Fabric SQL
7. **B17** -- No caching on analytics endpoints
8. **B18** -- No caching on dashboard stats
9. **B23** -- Blocking MinIO sync calls in async context
10. **D1** -- Missing composite index on engagement_metrics (brand_id, fetched_at)
11. **D13** -- Per-row commit during BC product sync (500 commits for 500 products)
12. **F12** -- Next.js image optimization completely disabled

### MEDIUM (Fix within 2 sprints)
13. **B3** -- N+1 in list_categories()
14. **B5** -- N+1 in reorder_calendar_items()
15. **B6** -- Sequential batch image fetch (no concurrency)
16. **B8** -- Unbounded posting heatmap query
17. **B11** -- No max limit cap on pagination
18. **B15** -- New Valkey connection per health check
19. **B21** -- No cache headers on brand logo serving
20. **B24** -- Blocking Qdrant sync calls
21. **B27** -- No rate limiting on AI endpoints
22. **D2** -- Missing composite index for engagement JOIN queries
23. **D3** -- Missing partial index for published calendar items
24. **D4** -- Missing composite index on agent_runs
25. **D12** -- Split transaction in brand update
26. **D14** -- Per-product commit in batch image fetch
27. **F1** -- KanbanBoard inline filtering (9 passes per render)
28. **F2** -- CalendarView getItemsForDay (30+ filter passes per render)
29. **F7** -- recharts in main bundle (no dynamic import)
30. **F8** -- dnd-kit in main bundle (no dynamic import)
31. **F13** -- Product/logo images not using next/image
32. **F19** -- SSE notification polling does not scale

### LOW (Backlog)
33. **B4** -- Missing eager load on content calendar duplicate endpoint
34. **B9** -- No limit on competitor list
35. **B25** -- Sync MinIO call during startup
36. **B28** -- No request body size middleware
37. **D5-D7** -- Additional composite indexes for less frequent queries
38. **D8-D10** -- Pagination improvements (keyset, total counts)
39. **F3-F6** -- Component memoization, effect cleanup
40. **F10** -- react-markdown dynamic import
41. **F15-F16** -- Minor memoization improvements
42. **F18** -- Calendar overlay portal

---

## Duplicate / Dead Code

| # | Location | Issue |
|---|----------|-------|
| X1 | `api/v1/content.py:19-43` `content_calendar()` | Duplicate of `api/v1/calendar.py` upcoming endpoint. The content version lacks eager loading and brand name. One should be removed. |
| X2 | `api/v1/content.py:46-79` `content_calendar_upcoming()` | Near-duplicate of `api/v1/calendar.py:30-65` `upcoming_calendar_items()`. The calendar version includes brand eager loading. Remove the content version. |
| X3 | `api/v1/system.py:102-121` `list_scheduler_jobs()` vs `system.py:323-337` `list_scheduler_jobs_detail()` | Two nearly identical endpoints for listing scheduler jobs. Consolidate into one. |
