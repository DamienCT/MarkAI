# Phase 7: API Contract & Endpoint Audit

**Date:** 2026-03-30
**Scope:** All HTTP endpoints registered in the MARKAI FastAPI backend
**Auditor:** Claude Opus 4.6

---

## 7.1 Endpoint Discovery

### Router Registration (backend/app/api/router.py)

All v1 routers are mounted under the `api_router` with prefix `/api/v1`. The `api_router` is included in the FastAPI app via `app.include_router(api_router)` in `backend/app/main.py`.

There is also one inline endpoint defined directly in `router.py`:
- `GET /api/v1/audit` -- alias for audit log listing

And one top-level endpoint in `main.py`:
- `GET /health` -- unauthenticated Docker healthcheck

### Authentication Mechanism

All authenticated endpoints use `Depends(get_current_user)` which:
1. Extracts a Bearer JWT from the `Authorization` header via `HTTPBearer`
2. Validates it as an Entra ID (Azure AD) token
3. Auto-provisions users on first login (admin if in security group, inactive viewer otherwise)
4. Rejects inactive users with 403

### Authorization / Role Hierarchy

| Role    | Level |
|---------|-------|
| admin   | 100   |
| manager | 80    |
| editor  | 60    |
| viewer  | 10    |

`role_has_access(user_role, required_role)` checks `user_level >= required_level`.

### Rate Limiting

**FINDING [CRITICAL]: No rate limiting is implemented anywhere in the backend.** There is no middleware, no dependency, and no decorator for rate limiting on any endpoint. This exposes the API to abuse, particularly on expensive endpoints like AI generation (`/intelligence/generate-fields`, `/intelligence/rewrite-field`, `/products/fetch-images`).

---

## 7.2 Complete Endpoint Inventory

### Top-Level (main.py)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 1 | GET | `/health` | None | -- | None | `{"status":"ok"}` | Docker healthcheck |

### Brands (`/api/v1/brands`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 2 | GET | `/brands/bc-companies` | JWT | viewer | None | `list[str]` | BC integration |
| 3 | GET | `/brands/bc-locations` | JWT | viewer | query: `company` (required) | `list[str]` | BC integration |
| 4 | GET | `/brands/` | JWT | viewer | query: `is_active`, `skip`, `limit` | `list[BrandResponse]` | Paginated |
| 5 | GET | `/brands/{brand_id}` | JWT | viewer | path: UUID | `BrandResponse` | 404 if missing |
| 6 | POST | `/brands/` | JWT | manager | body: `BrandCreate` | `BrandResponse` (201) | Checks slug uniqueness (409) |
| 7 | PUT | `/brands/{brand_id}` | JWT | manager | body: `BrandUpdate` | `BrandResponse` | Cancels running agents on deactivate |
| 8 | POST | `/brands/{brand_id}/complete-onboarding` | JWT | viewer | path: UUID | `BrandResponse` | Validates onboarding steps (422) |
| 9 | POST | `/brands/{brand_id}/activate` | JWT | viewer | path: UUID | `dict` | Starts content factory pipeline (409 if already activating) |
| 10 | GET | `/brands/{brand_id}/channels` | JWT | viewer | path: UUID | `list[dict]` | Channel config with status |
| 11 | PUT | `/brands/{brand_id}/channels` | JWT | manager | body: `ChannelConfigUpdate` | `dict` | Updates channel config |
| 12 | POST | `/brands/{brand_id}/logos` | JWT | manager | multipart: `file`, query: `label` | `dict` | 5MB limit, type validation |
| 13 | GET | `/brands/{brand_id}/logos/{label}` | **None** | -- | path: UUID, label | binary (image) | **UNAUTHENTICATED** |
| 14 | DELETE | `/brands/{brand_id}/logos/{label}` | JWT | manager | path: UUID, label | `{"status":"ok"}` | Deletes from MinIO |
| 15 | DELETE | `/brands/{brand_id}` | JWT | admin | path: UUID | 204 No Content | Hard delete |
| 16 | GET | `/brands/{brand_id}/competitors` | JWT | viewer | path: UUID | `list[CompetitorResponse]` | No pagination |
| 17 | POST | `/brands/{brand_id}/competitors` | JWT | manager | body: `CompetitorCreateBody` | `CompetitorResponse` (201) | |
| 18 | PUT | `/brands/{brand_id}/competitors/{id}` | JWT | manager | body: `CompetitorUpdate` | `CompetitorResponse` | |
| 19 | DELETE | `/brands/{brand_id}/competitors/{id}` | JWT | manager | path: UUIDs | 204 No Content | |

### Campaigns (`/api/v1/campaigns`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 20 | GET | `/campaigns/` | JWT | viewer | query: `brand_id`, `status_filter`, `skip`, `limit` | `list[CampaignResponse]` | Paginated |
| 21 | GET | `/campaigns/{campaign_id}` | JWT | viewer | path: UUID | `CampaignResponse` | |
| 22 | POST | `/campaigns/` | JWT | manager | body: `CampaignCreate` | `CampaignResponse` (201) | |
| 23 | PUT | `/campaigns/{campaign_id}` | JWT | manager | body: `CampaignUpdate` | `CampaignResponse` | Validates objective values |
| 24 | DELETE | `/campaigns/{campaign_id}` | JWT | manager | path: UUID | 204 No Content | |

### Content (`/api/v1/content`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 25 | GET | `/content/calendar` | JWT | viewer | query: `brand_id`, `month` | `list[dict]` | Max 200 items |
| 26 | GET | `/content/calendar/upcoming` | JWT | viewer | query: `limit` | `list[dict]` | |
| 27 | GET | `/content/` | JWT | viewer | query: `brand_id`, `is_current`, `skip`, `limit` | `list[ContentResponse]` | |
| 28 | GET | `/content/{content_id}` | JWT | viewer | path: UUID | `ContentResponse` | |
| 29 | POST | `/content/` | JWT | editor | body: `ContentCreate` | `ContentResponse` (201) | |
| 30 | PUT | `/content/{content_id}` | JWT | editor | body: `ContentUpdate` | `ContentResponse` | Validates status transitions (422) |
| 31 | POST | `/content/{content_id}/transition` | JWT | editor | path: UUID, query: `new_status` | `ContentResponse` | Status machine transition |

### Dashboard (`/api/v1/dashboard`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 32 | GET | `/dashboard/stats` | JWT | viewer | None | `dict` | Aggregate counts |

### Learning (`/api/v1/learning`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 33 | GET | `/learning/adaptations` | JWT | viewer | query: `skip`, `limit` | `list[dict]` | |

### Prompts (`/api/v1/prompts`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 34 | GET | `/prompts/` | JWT | viewer | query: `category`, `is_active`, `skip`, `limit` | `list[PromptVersionResponse]` | |
| 35 | GET | `/prompts/{prompt_id}` | JWT | viewer | path: UUID | `PromptVersionResponse` | |
| 36 | POST | `/prompts/` | JWT | manager | body: `PromptVersionCreate` | `PromptVersionResponse` (201) | |
| 37 | PUT | `/prompts/{prompt_id}` | JWT | manager | body: `PromptVersionUpdate` | `PromptVersionResponse` | |
| 38 | POST | `/prompts/{prompt_id}/activate` | JWT | manager | path: UUID | `PromptVersionResponse` | |
| 39 | POST | `/prompts/{prompt_id}/deactivate` | JWT | manager | path: UUID | `PromptVersionResponse` | |
| 40 | POST | `/prompts/ab-select` | JWT | viewer | query: `category`, `slug` | `PromptVersionResponse` | A/B testing selection |

### Providers (`/api/v1/providers`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 41 | GET | `/providers/categories` | JWT | viewer | None | `list[dict]` | AI model categories |
| 42 | GET | `/providers/models` | JWT | viewer | query: `category` | `list[AIModelResponse]` | |
| 43 | GET | `/providers/active` | JWT | viewer | None | `{"models": dict}` | Active model per category |
| 44 | PUT | `/providers/active/{category_slug}` | JWT | admin | body: `AIModelSelectionUpdate` | `AIModelSelectionResponse` | |
| 45 | POST | `/providers/discover` | JWT | admin | None | `DiscoverModelsResponse` | Calls OpenAI API |
| 46 | GET | `/providers/health` | JWT | viewer | None | `dict` | LiteLLM proxy health |

### Users (`/api/v1/users`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 47 | GET | `/users/search` | JWT | admin | query: `q` (min_length=1) | `list[EntraUserResult]` | Entra ID search |
| 48 | POST | `/users/grant-access` | JWT | admin | body: `GrantAccessRequest` | `GrantAccessResult` | Bulk user provisioning |
| 49 | GET | `/users/security-group-members` | JWT | manager | None | `list[str]` | Entra group member IDs |
| 50 | GET | `/users/me` | JWT | viewer | None | `UserResponse` | Current user |
| 51 | GET | `/users/` | JWT | manager | query: `skip`, `limit` | `list[UserResponse]` | |
| 52 | GET | `/users/{user_id}` | JWT | manager | path: UUID | `UserResponse` | |
| 53 | POST | `/users/` | JWT | admin | body: `UserCreate` | `UserResponse` (201) | Checks uniqueness (409) |
| 54 | PUT | `/users/{user_id}` | JWT | admin | body: `UserUpdate` | `UserResponse` | |
| 55 | PATCH | `/users/{user_id}` | JWT | admin | body: `UserUpdate` | `UserResponse` | Duplicate of PUT |

### Analytics (`/api/v1/analytics`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 56 | GET | `/analytics/summary` | JWT | viewer | None | `dict` | Aggregate metrics |
| 57 | GET | `/analytics/engagement/timeseries` | JWT | viewer | query: `days`, `brand_id` | `list[dict]` | |
| 58 | GET | `/analytics/posting/heatmap` | JWT | viewer | None | `list[dict]` | |
| 59 | GET | `/analytics/content/top` | JWT | viewer | query: `limit` | `list[dict]` | |
| 60 | GET | `/analytics/brands/{brand_id}/metrics` | JWT | viewer | path: UUID | `dict` | |

### Notifications (`/api/v1/notifications`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 61 | GET | `/notifications/` | JWT | viewer | query: `read`, `skip`, `limit` | `list[dict]` | User-scoped |
| 62 | GET | `/notifications/stream` | JWT | viewer | None | SSE stream | 10s polling interval |

### Settings (`/api/v1/settings`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 63 | GET | `/settings/` | JWT | viewer | None | `dict` | Key-value pairs |
| 64 | PUT | `/settings/` | JWT | admin | body: `dict` (untyped) | `dict` | Upsert key-value pairs |

### Agents (`/api/v1/agents`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 65 | GET | `/agents/runs` | JWT | viewer | query: `skip`, `limit`, `brand_id`, `trigger` | `list[dict]` | |

### Products (`/api/v1/products`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 66 | POST | `/products/sync/{brand_id}` | JWT | manager | path: UUID | `dict` (202) | BC product sync |
| 67 | GET | `/products/` | JWT | viewer | query: `brand_id`, `is_new`, `is_expiring`, `is_active`, `skip`, `limit` | `list[ProductResponse]` | |
| 68 | GET | `/products/{product_id}` | JWT | viewer | path: UUID | `ProductResponse` | |
| 69 | POST | `/products/` | JWT | manager | body: `ProductCreate` | `ProductResponse` (201) | |
| 70 | PUT | `/products/{product_id}` | JWT | manager | body: `ProductUpdate` | `ProductResponse` | |
| 71 | POST | `/products/{product_id}/upload-image` | JWT | manager | multipart: `file` | `ProductResponse` | No file size/type validation |
| 72 | POST | `/products/sync` | JWT | manager | None | `dict` (202) | Manual BC sync trigger |
| 73 | POST | `/products/{product_id}/fetch-images` | JWT | editor | path: UUID | `dict` | Web image search via Gemini |
| 74 | POST | `/products/batch-fetch-images` | JWT | editor | body: `FetchImagesRequest` | `dict` | Batch image fetch |
| 75 | GET | `/products/{product_id}/images` | JWT | viewer | path: UUID | `dict` | Image gallery |
| 76 | DELETE | `/products/{product_id}/images/{idx}` | JWT | editor | path: UUID, int | `dict` | Delete by index |
| 77 | PUT | `/products/{product_id}/images/{idx}/set-primary` | JWT | editor | path: UUID, int | `dict` | |

### Calendar (`/api/v1/calendar`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 78 | GET | `/calendar/upcoming` | JWT | viewer | query: `limit` | `list[dict]` | With brand join |
| 79 | GET | `/calendar/` | JWT | viewer | query: `brand_id`, `start_date`, `end_date`, `status_filter`, `skip`, `limit` | `list[CalendarItemResponse]` | |
| 80 | GET | `/calendar/{item_id}` | JWT | viewer | path: UUID | `CalendarItemResponse` | |
| 81 | POST | `/calendar/` | JWT | editor | body: `CalendarItemCreate` | `CalendarItemResponse` (201) | |
| 82 | PUT | `/calendar/{item_id}` | JWT | editor | body: `CalendarItemUpdate` | `CalendarItemResponse` | |
| 83 | DELETE | `/calendar/{item_id}` | JWT | editor | path: UUID | 204 No Content | |
| 84 | POST | `/calendar/reorder` | JWT | editor | body: `list[CalendarReorderItem]` | `list[CalendarItemResponse]` | Drag-and-drop |

### Webhooks (`/api/v1/webhooks`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 85 | POST | `/webhooks/publish-result` | Webhook Secret | -- | header: `X-Webhook-Secret`, body: `PublishResultPayload` | `dict` | n8n callback |

### Files (`/api/v1/files`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 86 | GET | `/files/{file_path:path}` | **None** | -- | path: string | binary | **UNAUTHENTICATED** MinIO proxy |

### Approvals (`/api/v1/approvals`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 87 | GET | `/approvals/` | JWT | viewer | query: `status_filter`, `skip`, `limit` | `{"items":[], "total":N, ...}` | Paginated with total |
| 88 | GET | `/approvals/pending` | JWT | viewer | query: `reviewer_id`, `skip`, `limit` | `list[ApprovalResponse]` | |
| 89 | GET | `/approvals/content/{content_id}` | JWT | viewer | path: UUID | `list[ApprovalResponse]` | |
| 90 | GET | `/approvals/{approval_id}` | JWT | viewer | path: UUID | `ApprovalResponse` | |
| 91 | POST | `/approvals/` | JWT | editor | body: `ApprovalCreate` | `ApprovalResponse` (201) | |
| 92 | POST | `/approvals/{id}/decide` | JWT | manager | body: `ApprovalDecision` | `ApprovalResponse` | Validates decision values |

### System (`/api/v1/system`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 93 | GET | `/system/health` | JWT | viewer | None | `HealthResponse` | Checks all dependencies |
| 94 | GET | `/system/jobs` | JWT | manager | None | `list[JobInfo]` | APScheduler jobs |
| 95 | POST | `/system/jobs/{job_id}/trigger` | JWT | admin | path: string | `dict` | Manually trigger job |
| 96 | GET | `/system/audit-log` | JWT | manager | query: `user_id`, `entity_type`, `action`, `skip`, `limit` | `list[dict]` | |
| 97 | GET | `/system/job-log` | JWT | manager | query: `job_name`, `status_filter`, `skip`, `limit` | `list[dict]` | |
| 98 | GET | `/system/services` | JWT | viewer | None | `list[dict]` | Service health + latency |
| 99 | GET | `/system/scheduler/jobs` | JWT | viewer | None | `list[dict]` | Duplicate of #94 but no auth check |
| 100 | GET | `/system/queues` | JWT | viewer | None | `list[dict]` | NATS stream info |

### Intelligence (`/api/v1/intelligence`)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 101 | GET | `/intelligence/reports` | JWT | viewer | query: `limit`, `type` | `list[dict]` | Agent run reports |
| 102 | GET | `/intelligence/report/{run_id}` | JWT | viewer | path: UUID | `dict` | Single report with brand info |
| 103 | GET | `/intelligence/trends` | JWT | viewer | query: `brand_id` | `list[dict]` | From strategy output |
| 104 | GET | `/intelligence/research/{brand_id}` | JWT | viewer | path: UUID | `dict` | Research runs + competitors |
| 105 | GET | `/intelligence/adaptations/{content_id}` | JWT | viewer | query: `status_filter`, `skip`, `limit` | `list[dict]` | |
| 106 | POST | `/intelligence/trigger/research` | JWT | manager | body: `WorkflowTrigger` | `dict` | NATS publish |
| 107 | POST | `/intelligence/trigger/strategy` | JWT | manager | body: `WorkflowTrigger` | `dict` | NATS publish |
| 108 | POST | `/intelligence/trigger/content` | JWT | editor | body: `WorkflowTrigger` | `dict` | NATS publish |
| 109 | POST | `/intelligence/generate-fields` | JWT | editor | body: `AIGenerateFieldRequest` | `AIGenerateFieldResponse` | LLM call |
| 110 | POST | `/intelligence/rewrite-field` | JWT | editor | body: `AIRewriteFieldRequest` | `AIRewriteFieldResponse` | LLM call |

### Audit (inline in router.py)

| # | Method | Path | Auth | Min Role | Request Validation | Response Format | Notes |
|---|--------|------|------|----------|-------------------|-----------------|-------|
| 111 | GET | `/audit` | JWT | viewer | query: `page`, `limit` | `list[dict]` | Alias for audit log |

**Total: 111 endpoints**

---

## 7.3 Findings

### CRITICAL Issues

#### C1: No Rate Limiting
**Severity: CRITICAL**
No rate limiting middleware or per-endpoint throttling exists anywhere. Endpoints that call external APIs or perform expensive LLM operations (`/intelligence/generate-fields`, `/intelligence/rewrite-field`, `/products/fetch-images`, `/products/batch-fetch-images`, `/providers/discover`) are especially vulnerable to cost-based abuse.

**Recommendation:** Add a rate limiting middleware (e.g., `slowapi` or custom Valkey-based limiter). At minimum, protect LLM-calling endpoints with per-user rate limits (e.g., 10 req/min).

#### C2: Unauthenticated File Proxy
**Severity: HIGH**
`GET /api/v1/files/{file_path:path}` serves any MinIO object without authentication. The endpoint comment says "object paths contain UUIDs and are not guessable," but this is security-by-obscurity. Anyone who obtains or guesses a file path can access all stored files including brand logos, product images, and any uploaded content.

**File:** `backend/app/api/v1/files.py`

**Recommendation:** Add authentication or implement signed URLs with expiration. At minimum, scope access to the user's brands.

#### C3: Unauthenticated Logo Endpoint
**Severity: MEDIUM**
`GET /api/v1/brands/{brand_id}/logos/{label}` has no `Depends(get_current_user)` unlike every other brand endpoint. Same security-by-obscurity concern as C2.

**File:** `backend/app/api/v1/brands.py`, line 310-333

#### C4: Missing Authorization on Sensitive Brand Operations
**Severity: HIGH**
- `POST /brands/{brand_id}/complete-onboarding` requires only **viewer** role. Any authenticated viewer can complete onboarding for any brand.
- `POST /brands/{brand_id}/activate` requires only **viewer** role. Any authenticated viewer can start the content factory pipeline for any brand, triggering expensive LLM agent chains.

**File:** `backend/app/api/v1/brands.py`, lines 123-200

**Recommendation:** Both should require **manager** role minimum.

### HIGH Issues

#### H1: Duplicate Scheduler Jobs Endpoint
**Severity: MEDIUM**
Two endpoints list scheduler jobs:
- `GET /api/v1/system/jobs` -- requires **manager** role
- `GET /api/v1/system/scheduler/jobs` -- requires only **viewer** role

The second endpoint (`/system/scheduler/jobs`) exposes the same information but with weaker access control. This is likely unintentional.

**File:** `backend/app/api/v1/system.py`, lines 102-121 vs 323-337

#### H2: Duplicate Audit Log Endpoint
**Severity: LOW**
Two endpoints serve audit logs:
- `GET /api/v1/system/audit-log` -- requires **manager** role, has filtering
- `GET /api/v1/audit` -- requires only **viewer** role, no filtering

The inline `/audit` endpoint has weaker access control than `/system/audit-log`.

**File:** `backend/app/api/router.py`, lines 59-80

#### H3: Duplicate PUT/PATCH on Users
**Severity: LOW**
`PUT /users/{user_id}` and `PATCH /users/{user_id}` are functionally identical -- both use `UserUpdate` with `exclude_unset=True`. The PATCH is technically correct semantics but having both is redundant.

**File:** `backend/app/api/v1/users.py`, lines 253-299

#### H4: Duplicate Calendar Upcoming Endpoints
**Severity: LOW**
Two overlapping upcoming calendar endpoints:
- `GET /api/v1/content/calendar/upcoming` (in content.py)
- `GET /api/v1/calendar/upcoming` (in calendar.py)

Both return upcoming calendar items with nearly identical logic. The `/calendar/upcoming` version includes brand name via join.

#### H5: Settings PUT Accepts Untyped dict
**Severity: MEDIUM**
`PUT /api/v1/settings/` accepts a bare `dict` as the request body with no Pydantic schema validation. Any JSON object will be accepted and written to the database.

**File:** `backend/app/api/v1/settings.py`, line 27

#### H6: Product Image Upload Has No Size/Type Validation
**Severity: MEDIUM**
`POST /products/{product_id}/upload-image` accepts any file without checking content type or file size. Compare to the brand logo upload which validates both (5MB limit, image types only).

**File:** `backend/app/api/v1/products.py`, lines 143-177

### MEDIUM Issues

#### M1: Inconsistent Response Formats for List Endpoints
Several patterns are used for list responses across the API:
- **Paginated with total count:** Only `GET /approvals/` returns `{"items":[], "total":N, "skip":N, "limit":N}`
- **Simple array:** Most list endpoints return bare `list[]` with `skip`/`limit` query params
- **No total count:** All other list endpoints lack a total count, forcing clients to fetch-until-empty

**Recommendation:** Standardize on a wrapper like `{"items":[], "total":N, "page":N, "limit":N}` for all list endpoints.

#### M2: No Maximum Limit Cap on Pagination
Most list endpoints accept `limit` as a query parameter with a default (usually 100 or 200) but no maximum cap. A client can request `limit=999999` and retrieve the entire table in one query.

Affected: All list endpoints with `limit` parameter (brands, campaigns, content, products, approvals, users, etc.)

**Recommendation:** Add `limit = min(limit, MAX_LIMIT)` clamping.

#### M3: Content Transition Uses Query Parameter Instead of Body
`POST /content/{content_id}/transition` takes `new_status` as a **query parameter** rather than a request body. For a POST endpoint that changes state, the status should be in the request body.

**File:** `backend/app/api/v1/content.py`, line 138

#### M4: No Delete Endpoint for Content
Content has full CRUD except DELETE. While this may be intentional (content should be archived, not deleted), it's worth documenting.

#### M5: `type` Shadows Python Builtin
`GET /intelligence/reports` uses `type: str | None = None` as a query parameter name, which shadows the Python `type` builtin.

**File:** `backend/app/api/v1/intelligence.py`, line 78

#### M6: SSE Notification Stream Has No Heartbeat Mechanism
The `/notifications/stream` SSE endpoint polls every 10 seconds and sends data, but has no heartbeat/keep-alive comments. Proxies may close the connection due to inactivity if all notifications are read.

**File:** `backend/app/api/v1/notifications.py`, lines 57-96

#### M7: No Mark-as-Read Endpoint for Notifications
Notifications can be listed and streamed but there is no endpoint to mark them as read.

#### M8: Webhook Secret Error Returns 503 Instead of 500
When `N8N_WEBHOOK_SECRET` is not configured, the publish-result webhook returns 503 (Service Unavailable). This is semantically correct but the error message leaks internal configuration state.

**File:** `backend/app/api/v1/webhooks.py`, line 25

### LOW Issues

#### L1: Raw SQL in Multiple Endpoints
Several endpoints use raw SQL via `text()` instead of ORM queries:
- `dashboard.py` -- all queries
- `analytics.py` -- all queries
- `settings.py` -- all queries
- `system.py` -- health check
- `intelligence.py` -- timezone lookup

While parameterized (safe from SQL injection), this creates maintenance burden and bypasses ORM validation.

#### L2: No OpenAPI Description on Many Endpoints
Many endpoints lack docstrings, which means their OpenAPI description is empty. FastAPI auto-generates the schema from Pydantic models but the endpoint descriptions are absent for approximately 40% of endpoints.

#### L3: Inconsistent Error Response Structure
Most endpoints raise `HTTPException(detail="...")` which produces `{"detail": "message"}`. However, the global exception handler returns `{"detail": "Internal server error"}` for unhandled exceptions. The approval list endpoint returns a different structure `{"items":[], "total":N}`. There is no standardized error envelope.

#### L4: `analytics/engagement/timeseries` Uses MAKE_INTERVAL
The `MAKE_INTERVAL(days => :days)` syntax is PostgreSQL-specific. While this project only targets PostgreSQL, it's worth noting for portability.

#### L5: Brand Logo GET Returns 404 with Generic Message
Both "brand not found" and "logo not found" paths return 404, but they could be distinguished for better debugging.

---

## 7.4 API Documentation Assessment

### OpenAPI / Swagger

FastAPI auto-generates OpenAPI at `/docs` (Swagger UI) and `/redoc` (ReDoc). The spec is available at `/openapi.json`.

**Quality Assessment:**
- **Schemas:** Good coverage where Pydantic response_model is used. ~60% of endpoints specify `response_model`, which produces accurate schemas.
- **Missing schemas:** Many endpoints return manually-constructed dicts (e.g., analytics, dashboard, intelligence, agents, notifications). These show as `Response[200]: Successful Response` with no schema.
- **Auth:** Shown correctly as Bearer HTTP auth
- **Tags:** All endpoints are properly tagged by module
- **Status codes:** Correctly annotated for 201 (create) and 204 (delete) where used

---

## 7.5 Summary

| Category | Count |
|----------|-------|
| Total Endpoints | 111 |
| Authenticated (JWT) | 107 |
| Unauthenticated | 3 (health, files proxy, brand logo GET) |
| Webhook-secret protected | 1 |
| With Pydantic response_model | ~65 |
| With manual dict response | ~46 |
| CRITICAL findings | 4 (C1-C4) |
| HIGH findings | 6 (H1-H6) |
| MEDIUM findings | 8 (M1-M8) |
| LOW findings | 5 (L1-L5) |

### Priority Remediation Order

1. **C4** -- Add manager role check to complete-onboarding and activate endpoints (5 min fix)
2. **C1** -- Implement rate limiting, especially on LLM endpoints (2-4 hours)
3. **C2/C3** -- Add authentication or signed URLs to file/logo endpoints (1-2 hours)
4. **H1/H2** -- Remove duplicate endpoints with weaker auth (15 min)
5. **H5** -- Add Pydantic schema for settings update (15 min)
6. **H6** -- Add file size/type validation to product image upload (15 min)
7. **M1/M2** -- Standardize pagination with total counts and limit caps (2-3 hours)
8. **M7** -- Add notification mark-as-read endpoint (30 min)
