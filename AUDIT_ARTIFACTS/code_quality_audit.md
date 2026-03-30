# Phase 10 — Code Quality, Patterns & Architecture Audit

**Date:** 2026-03-30
**Scope:** Backend, Agents, Frontend, Notifications, Browser-Worker
**Rating Legend:** PASS | WARN | FAIL

---

## 10.1 Architecture Patterns

### Pattern Identification

| Layer | Pattern | Consistency |
|-------|---------|-------------|
| **Backend** | 3-Layer: Router -> Service -> Model (FastAPI) | WARN — partially applied |
| **Agents** | LangGraph State-Machine Workflows (state/graph/nodes) | PASS — very consistent |
| **Frontend** | Next.js App Router + Domain Components + Shared UI | PASS |
| **Infra** | Multi-service Docker Compose with NATS message bus | PASS |

**Overall Architecture: Event-Driven Microservices + LangGraph Pipelines**

The system uses a well-defined architecture:
- **Backend (FastAPI)** — REST API, auth, scheduling, CRUD
- **Agents (LangGraph)** — AI workflows consumed from NATS JetStream
- **Browser-Worker** — Playwright-based scraping microservice
- **Notifications** — SSE + Teams webhook microservice
- **Frontend (Next.js)** — React SPA with Azure AD SSO

### Separation of Concerns

| Aspect | Rating | Detail |
|--------|--------|--------|
| API vs Business Logic | WARN | Some route handlers contain significant business logic inline (e.g., `brands.py` has ~80-line `activate_content_factory` with NATS publish, `analytics.py` has raw SQL in route handlers) |
| Service Layer | WARN | Service layer exists for brands/content/approvals/products but is **thin CRUD wrappers only**. Analytics, dashboard, agents, calendar, intelligence, learning routes bypass services entirely and query DB directly in route handlers |
| Model Layer | PASS | Clean SQLAlchemy 2.0 mapped models with proper relationships |
| Schema Layer | PASS | Pydantic v2 schemas for request/response validation |
| Agents vs Backend | PASS | Clean boundary — agents communicate only via NATS messages and direct DB queries |

### Service Layer Gaps (Routes That Bypass Services)

These routes contain raw SQL or ORM queries directly in the handler, without a service layer:

| Route File | Issue |
|------------|-------|
| `analytics.py` | 5 endpoints with raw SQL inline (no service) |
| `dashboard.py` | Raw SQL `SELECT count(*)` queries inline |
| `agents.py` | Direct ORM query inline |
| `intelligence.py` | Mixed raw SQL + ORM + NATS publish inline |
| `learning.py` | Direct ORM inline |
| `notifications.py` | Direct session factory usage |
| `calendar.py` | Likely inline queries |
| `router.py` | Contains a full `/audit` endpoint with inline query at module level |

**Impact:** Business logic scattered across route handlers makes it harder to test and reuse. Only ~5 of ~20 route files delegate to a service module.

### Layer Boundary Violations

1. **`router.py` contains an endpoint** — The `/audit` route is defined directly in `router.py` alongside route registration. Should be in its own route file.

2. **Lazy imports inside route handlers** — Several files use `from app.services import X` inside function bodies (e.g., `brands.py:189`, `system.py:59`). This is sometimes done to avoid circular imports but indicates coupling issues.

3. **Agents use raw SQL via `shared/tools/database.py`** — The agents service maintains its own DB access layer using raw SQL (`text()`) rather than ORM models. This means the schema is duplicated: once in SQLAlchemy models (backend) and once in raw SQL strings (agents). Schema changes require updates in two places.

### Can Business Logic Be Tested Independently?

| Component | Testable? | Detail |
|-----------|-----------|--------|
| Service functions | PASS | Pure async functions with `db: AsyncSession` dependency injection |
| Workflow nodes | WARN | Functions take TypedDict state, but call external services (DB, LLM, browser) with no DI/interface — hard to mock |
| LLM calls | WARN | `shared/llm.py` is a module-level singleton; no interface abstraction for test doubles |
| Route handlers | FAIL | Many embed business logic + SQL, cannot be tested without full HTTP context |

---

## 10.2 Design Pattern Audit

### Patterns Used Correctly

| Pattern | Where | Assessment |
|---------|-------|------------|
| **State Machine** | LangGraph workflows (`graph.py`) | PASS — clean `_check_failed` conditional edges, consistent across all 7 workflows |
| **Pipeline / Chain** | `worker.py` CHAIN_NEXT mapping | PASS — well-structured with depth guards and conditional chaining |
| **Repository** | Service layer (`brand_service.py`, `content_service.py`) | PASS (where used) |
| **Dependency Injection** | FastAPI `Depends()` for DB session and auth | PASS |
| **Role-Based Access Control** | `permissions.py` with numeric hierarchy | PASS |
| **Retry with Backoff** | `shared/llm.py` using tenacity | PASS |
| **Singleton Settings** | Pydantic `Settings()` in both backend and agents | PASS |
| **Status Machine** | `content_service.py` `VALID_TRANSITIONS` dict | PASS |
| **Prompt Injection Defense** | `shared/sanitize.py` regex filtering | PASS |

### Anti-Patterns Identified

#### 1. God Function: `worker.py::_handle_message` — FAIL

**File:** `agents/worker.py` lines 80-345 (~265 lines)

This single function handles:
- Message parsing and validation
- Graph resolution and dispatch
- Agent run lifecycle tracking (create/complete)
- Idempotency checks
- Sequential content chaining with queue management
- Pipeline chaining (activation, evaluation, adaptation)
- Product intel conditional chaining
- Adaptation feedback loop with depth guards
- Timeout handling
- Error handling and status updates

**Recommendation:** Extract into smaller functions: `_dispatch_workflow()`, `_handle_chain()`, `_handle_sequential_content()`, etc.

#### 2. Raw SQL Duplication — WARN

The agents service (`shared/tools/database.py`) and the backend service layer both access the same database with different patterns:
- Backend: SQLAlchemy ORM models with proper relationships
- Agents: Raw SQL strings via `text()`

Functions like `store_content()`, `store_calendar_items()`, `store_adaptations()` in agents contain 50+ lines of raw SQL with manual field mapping, date parsing, and validation that could drift from the ORM schema.

#### 3. Feature Envy: Route Handlers Reaching Into Models — WARN

Several route handlers bypass the service layer and directly manipulate ORM objects:
- `brands.py:update_brand` does raw SQL `UPDATE agent_runs` after calling the service
- `brands.py:complete_onboarding` validates brand state and updates fields directly
- `approvals.py:list_approvals` imports and queries the Approval model directly

#### 4. Data Clump: Error Accumulation — WARN

All workflow states repeat the same error accumulation pattern:
```python
return {"status": "failed", "errors": [*(state.get("errors") or []), "error message"]}
```
This pattern is repeated ~30+ times across all node files. Should be a shared helper.

#### 5. Tight Coupling: `_consumer` Global — WARN

`worker.py` uses a module-level `_consumer: NATSConsumer | None = None` global that is accessed inside `_handle_message`. This makes the message handler tightly coupled to the module state.

### Workflow Structural Consistency — PASS

All 7 workflows follow the exact same pattern:

```
state.py     → TypedDict with total=False
graph.py     → StateGraph builder with _check_failed conditional edges
nodes.py     → Async functions returning dict updates
```

| Workflow | State File | Graph File | Nodes File | Consistent |
|----------|-----------|-----------|-----------|-----------|
| research | PASS | PASS | PASS | Yes |
| strategy | PASS | PASS (+ checkpointer) | PASS | Yes |
| planning | PASS | PASS | PASS | Yes |
| content | PASS | PASS | PASS (+ image_sourcing.py) | Yes |
| evaluation | PASS | PASS | PASS | Yes |
| adaptation | PASS | PASS (+ checkpointer) | PASS | Yes |
| product_intel | PASS | PASS | PASS | Yes |

**Observation:** `shared/state.py` defines a `BaseState` TypedDict with the common fields, but no workflow state actually inherits from it. Each re-declares `brand_id`, `run_id`, `status`, `errors`, `messages` independently. This is a missed DRY opportunity.

---

## 10.3 Code Consistency

### Coding Style

| Aspect | Backend (Python) | Agents (Python) | Frontend (TypeScript) |
|--------|-----------------|-----------------|----------------------|
| Naming | snake_case | snake_case | camelCase (TS standard) |
| Docstrings | Inconsistent (some files have them, some don't) | Good (module-level docstrings on all graph/state files) | JSDoc absent |
| Type hints | Good — Python 3.12 `X | None` syntax | Good | Good — TS interfaces in `types/index.ts` |
| Consistency | PASS | PASS | PASS |

### Linter Configuration

| Tool | Configured? | Enforced? |
|------|------------|-----------|
| **Ruff** (Python) | Listed in `dev` dependencies but **no `[tool.ruff]` config** in any `pyproject.toml` | FAIL — not enforced |
| **ESLint** (TypeScript) | `eslint.config.mjs` with Next.js core-web-vitals + typescript rules | PASS |
| **Prettier** | Not found | WARN — no formatter configured for frontend |
| **mypy** | Not configured | FAIL — no static type checking for Python |
| **Black/isort** | Not configured | N/A — Ruff would handle this if configured |

**Key Gap:** Ruff is a dev dependency but has zero configuration. No line length, no rule selection, no import sorting rules. It's essentially a no-op.

### Error Handling Consistency

| Pattern | Consistency | Detail |
|---------|-------------|--------|
| Backend route errors | PASS | Consistent `raise HTTPException(status_code=X, detail="...")` |
| Backend global handler | PASS | `global_exception_handler` sanitizes tracebacks, returns generic 500 |
| Agent workflow errors | WARN | Some nodes return `{"status": "failed", "errors": [...]}`, others use `logger.error()` + return empty dict. Not all nodes handle exceptions uniformly. |
| Agent worker errors | PASS | Good try/except with `complete_agent_run(status="failed")` and proper NAK/ACK |
| Frontend API errors | PASS | Centralized in `ApiClient.request()` — throws `ApiError` with status + detail |

### Logging Consistency

| Service | Logger Setup | Format | Level Control |
|---------|-------------|--------|---------------|
| Backend | `logging.getLogger(__name__)` per module | Default FastAPI | Via env |
| Agents worker | `logging.basicConfig()` at module level | Custom format with timestamps | Hardcoded INFO |
| Agents nodes | `logging.getLogger(__name__)` per module | Inherited from worker | Inherited |
| Browser-worker | `logging.getLogger("browser-worker")` | Default | Default |
| Notifications | `logging.getLogger("notifications")` | Default | Default |

**Issue:** No structured logging (JSON). No correlation IDs passed between services. The `run_id` is logged in the agents worker but not propagated as a correlation ID to LLM calls or browser-worker requests.

### API Response Format Consistency — WARN

The backend API does **not** use a consistent response envelope. Different endpoints return different shapes:

| Endpoint | Response Shape |
|----------|---------------|
| `GET /brands/` | `BrandResponse[]` (Pydantic model) |
| `GET /approvals/` | `{"items": [...], "total": N, "skip": N, "limit": N}` (paginated) |
| `GET /agents/runs` | `[{...}]` (raw dict list — no Pydantic, no pagination envelope) |
| `GET /dashboard/stats` | `{key: value}` (flat dict) |
| `GET /analytics/summary` | `{key: value}` (flat dict) |
| `GET /content/calendar` | `[{...}]` (manually serialized dicts — no Pydantic) |
| `POST /brands/{id}/activate` | `{"status": ..., "brand_id": ..., "message": ...}` |
| `PUT /brands/{id}/channels` | `{"status": "ok", "channels": {...}}` |

**Problems:**
1. Some endpoints use `response_model=` Pydantic serialization, others return raw dicts
2. Pagination is inconsistent — only `approvals` uses an envelope; `agents/runs` uses query params but returns a flat list
3. Success responses mix `{"status": "ok"}` with Pydantic models
4. Calendar endpoints manually serialize with inline dict comprehensions instead of schemas

---

## 10.4 Testing Architecture

### Testing Framework

| Layer | Framework | Config File | Tests Found |
|-------|-----------|------------|-------------|
| Backend | pytest + pytest-asyncio (dev dep) | None | **ZERO** |
| Agents | None | None | **ZERO** |
| Frontend | None configured | None | **ZERO** |
| Browser-worker | None | None | **ZERO** |
| Notifications | None | None | **ZERO** |
| Eval (promptfoo) | promptfoo | `eval/promptfooconfig.yaml` | Prompt evaluation tests (not unit tests) |

### Test Coverage: 0%

**There are zero automated tests in this entire codebase.**

- No unit tests
- No integration tests
- No API endpoint tests
- No component tests
- No E2E tests
- No `conftest.py`, no `jest.config.*`, no `vitest.*`
- No CI pipeline to run tests
- `pytest` and `pytest-asyncio` are listed as dev dependencies in backend but never used

### What Tests Are MISSING (Critical)

#### Priority 1 — Must Have
| Test | Why |
|------|-----|
| Auth flow (JWT validation, role checking) | Security-critical — `get_current_user` auto-provisions users |
| Content status transitions | `VALID_TRANSITIONS` state machine has complex rules |
| Brand onboarding validation | Business logic validates multiple conditions |
| NATS message handling | `_handle_message` is the core workflow dispatcher |
| LLM response parsing | `parse_llm_json` handles malformed JSON from LLMs |
| API endpoint smoke tests | Verify all routes return expected status codes |

#### Priority 2 — Should Have
| Test | Why |
|------|-----|
| Workflow graph structure | Verify each graph compiles and has expected nodes/edges |
| Service layer CRUD | `brand_service`, `content_service`, `approval_service` |
| Permission checks | `role_has_access()` role hierarchy |
| Sanitization | `sanitize_for_prompt` injection patterns |
| Calendar item storage | Complex date parsing and channel validation in `store_calendar_items` |

#### Priority 3 — Nice to Have
| Test | Why |
|------|-----|
| Frontend component rendering | Dashboard, BrandOnboarding, ContentEditor |
| API client retry behavior | `tenacity` retry logic in `shared/llm.py` |
| Scheduler job registration | Verify all jobs are registered |
| E2E workflow pipeline | Full research -> strategy -> planning -> content chain |

---

## Cross-File Analyses

### Dependency Graph

#### Inter-Service Dependencies

```
Frontend ──HTTP──> Backend ──NATS──> Agents
                     │                  │
                     ├──HTTP──> Browser-Worker
                     ├──HTTP──> Notifications
                     │                  │
                     ├──SQL───> PostgreSQL <──SQL── Agents
                     ├──S3────> MinIO     <──S3─── Agents
                     ├──HTTP──> LiteLLM   <──HTTP─ Agents
                     └──HTTP──> Qdrant    <──HTTP─ Agents
```

#### Circular Dependencies: None Found

Python imports flow strictly downward:
- `api/v1/*` -> `services/*` -> `models/*` (backend)
- `workflows/*/nodes.py` -> `shared/tools/*` -> `shared/config.py` (agents)
- No circular imports detected.

#### Orphaned Files / Directories

| File/Dir | Status |
|----------|--------|
| `agents/app/` | **Listed in agents dir but empty/unused** — worker.py is at top level, agents use `shared/` and `workflows/` |
| `review/` | Contains `generate_posts.py` — appears to be a standalone script, not integrated |
| `eval/` | Contains promptfoo config — evaluation framework, partially integrated |
| `samples/` | Unknown purpose — not imported anywhere |
| `backend/alembic/versions/` | **Empty** — migrations directory exists but no migration files. Schema managed by `db/init.sql` only |
| `agents.log`, `backend.log`, `frontend.log` | Log files committed to repo |

### Data Flow: User Input to Storage

**Trace: User creates a brand and activates content factory**

```
1. Frontend: BrandForm.tsx -> api.post("/api/v1/brands/", brandData)
2. Backend Router: brands.py::create_brand() validates via BrandCreate schema
3. Backend Service: brand_service.create_brand() -> ORM insert -> PostgreSQL
4. Frontend: api.post("/api/v1/brands/{id}/activate")
5. Backend Router: brands.py::activate_content_factory()
   - Validates onboarding complete
   - Updates brand status to "activating"
   - nats_service.publish("research.trigger", {...})
6. NATS JetStream: delivers message to agents worker
7. Agents Worker: _handle_message() resolves research_graph
8. Research Graph: crawl_website -> analyze_social -> ... -> store_results
9. Each node: shared/tools/database.py raw SQL -> PostgreSQL
10. Worker: auto-chains to strategy.trigger -> planning.trigger -> content.generate
11. Content stored: shared/tools/database.py::store_content() -> PostgreSQL
```

**Input Validation Points:**
- Pydantic schema validation at API boundary (BrandCreate, BrandUpdate)
- `sanitize_for_prompt()` before LLM calls (prompt injection defense)
- Channel validation in `store_calendar_items()` (whitelist)
- File type/size validation in logo upload

**Gap:** No input validation in NATS message payloads consumed by agents. The `_handle_message` function trusts `brand_id` from the message without validating it's a real UUID or checking authorization.

### Error Propagation: Deep Stack to User

**Trace: LLM call fails during content generation**

```
1. content/nodes.py::generate_caption() calls chat_completion()
2. shared/llm.py::chat_completion() raises httpx.HTTPStatusError
3. tenacity retries 3 times with exponential backoff
4. If all retries fail, exception propagates to the node
5. Node catches Exception, returns {"status": "failed", "errors": [...]}
6. graph.py::_check_failed() routes to END
7. worker.py::_handle_message() catches Exception
8. complete_agent_run(run_id, status="failed", error_message=str(exc))
9. Frontend polls GET /api/v1/agents/runs -> sees status "failed"
```

**Issues:**
- Error messages stored in `agent_runs.error_message` may contain raw exception text with internal details (stack traces, URLs, config values)
- No structured error codes — frontend parses freetext `error_message`
- No notification triggered on workflow failure (notification service exists but is not called from the worker)

### Auth Flow: Protected Routes

**Every route protected?** YES (with caveats)

| Route | Protection | Notes |
|-------|-----------|-------|
| All `/api/v1/*` routes | `Depends(get_current_user)` | PASS |
| `GET /health` | **No auth** | Intentional — Docker healthcheck |
| `GET /brands/{id}/logos/{label}` | `Depends(get_db)` only | **FAIL — no auth!** Logo serving endpoint has no `get_current_user` dependency. Anyone can access brand logos if they know the brand ID and label. |
| NATS messages | No auth | Workers trust the message bus implicitly. NATS has no per-subject authorization configured. |
| Browser-worker endpoints | **No auth** | Internal service — relies on Docker network isolation |
| Notifications endpoints | **No auth** | Internal service — relies on Docker network isolation |

**Role Enforcement:**
- Write operations consistently check `role_has_access(current_user.role, "manager")` or `"editor"`
- Read operations only require authentication (any role)
- Admin-only: `delete_brand` requires `"admin"`
- `require_role` decorator exists but is **never used** — all routes use inline `role_has_access()` checks

---

## Summary of Findings

### Critical Issues (FAIL)

| # | Issue | Impact |
|---|-------|--------|
| 1 | **Zero automated tests** | No regression protection, no CI safety net |
| 2 | **Logo endpoint has no auth** | `GET /brands/{id}/logos/{label}` — public access to brand assets |
| 3 | **No linter enforcement** | Ruff is a dependency but unconfigured; no mypy |
| 4 | **Empty alembic/versions** | No migration history — schema changes are untracked |

### Significant Issues (WARN)

| # | Issue | Impact |
|---|-------|--------|
| 5 | Service layer applied to ~25% of routes | Business logic scattered in route handlers |
| 6 | Inconsistent API response format | No standard envelope, mixed Pydantic/raw dict responses |
| 7 | God function: `_handle_message` (265 lines) | Hard to maintain and test |
| 8 | Dual DB access: ORM (backend) vs raw SQL (agents) | Schema drift risk |
| 9 | No structured logging or correlation IDs | Hard to trace requests across services |
| 10 | No error notification from workflow failures | Failures are silent until user checks UI |
| 11 | WorkflowState classes don't inherit BaseState | DRY violation |
| 12 | Repeated error accumulation pattern across nodes | Should be a shared helper |
| 13 | NATS message payloads not validated | No schema validation on consumed messages |
| 14 | `require_role` decorator exists but is never used | Dead code / inconsistent pattern |

### Strengths

| # | Strength |
|---|----------|
| 1 | Workflow architecture is exceptionally consistent (7/7 follow same pattern) |
| 2 | Clean auth flow with Azure AD + auto-provisioning + security group checks |
| 3 | Good prompt injection defense in `sanitize.py` |
| 4 | Retry with exponential backoff on all LLM calls |
| 5 | Dynamic model resolution (not hardcoded) |
| 6 | Production startup guards (refuse to start with default secrets) |
| 7 | Content status state machine with validated transitions |
| 8 | Sequential content generation with queue management prevents overload |
| 9 | Pipeline chain depth guards prevent infinite loops |
| 10 | Frontend centralized API client with auth token injection |

---

## Recommendations (Prioritized)

### Immediate (Week 1)
1. **Add auth to logo endpoint** — Add `current_user: User = Depends(get_current_user)` to `get_brand_logo`
2. **Configure Ruff** — Add `[tool.ruff]` section with line-length, select rules, isort
3. **Add smoke tests** — pytest fixtures for DB session mock, test each route returns expected status

### Short-term (Weeks 2-4)
4. **Standardize API responses** — Create a response envelope (`{data, meta, errors}`) and apply consistently
5. **Extract service layer** — Move inline SQL from analytics, dashboard, agents, intelligence routes into services
6. **Refactor `_handle_message`** — Extract chaining logic into `ChainRouter` class
7. **Add Pydantic validation for NATS payloads** — Define message schemas in `shared/`
8. **Create BaseState inheritance** — Have all workflow states extend `shared.state.BaseState`

### Medium-term (Month 2)
9. **Add integration tests** — Test full workflow dispatch with mock LLM
10. **Structured logging** — JSON logs with request_id / run_id correlation
11. **Generate Alembic migrations** — Run `alembic revision --autogenerate` to capture current schema
12. **Workflow failure notifications** — Call notification service from `_handle_message` on failure
13. **Add mypy** — Configure strict type checking for backend and agents
