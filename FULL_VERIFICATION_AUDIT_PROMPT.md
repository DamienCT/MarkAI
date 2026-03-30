# MARKAI Verification Audit v3 — Convergence Audit

**Purpose:** Iterative convergence audit. Run audit passes in a loop until zero new issues are found. Each pass reads actual code, verifies previous fixes, and searches for remaining bugs. The loop stops ONLY when a complete pass finds nothing new.

**Prior audits:** v1 found 17 bugs (all fixed). v2 found 52 issues (28 fixed, 12 documented as architectural). This v3 audit verifies all prior fixes are correct and searches for anything missed.

**Reference:** `SEQUENCE_MAP.html`, `AUDIT_RESULTS.md` (prior findings)

---

## Loop Protocol

```
REPEAT:
  1. Run a full audit pass across ALL sections below
  2. For each check: read the actual code, verify correctness
  3. Collect all findings (bugs, regressions, edge cases, dead code)
  4. IF findings > 0:
     a. Fix every finding
     b. Record what was fixed
     c. GOTO step 1 (new pass to verify fixes + find more)
  5. IF findings == 0:
     a. Report "CONVERGED — zero issues found"
     b. STOP
```

**Rules:**
- Each pass must re-read code — do NOT rely on memory of prior passes
- A "finding" is any bug, logic error, regression, type mismatch, missing guard, or incorrect behavior
- Cosmetic issues (naming, comments, formatting) do NOT count as findings
- Documented architectural gaps from v2 do NOT count (they require design decisions)
- Each pass must check ALL sections, not just areas where bugs were previously found
- Report the pass number and findings count for each iteration

---

## Pass Checklist — All Sections

### Section A: v1+v2 Fix Regression Check

Verify every prior fix is still correct and hasn't introduced new bugs:

**v1 fixes to verify:**
- [ ] `backend/app/api/v1/webhooks.py` — webhook secret returns 503 when unconfigured (not silent pass-through)
- [ ] `backend/app/auth/models.py` — User `is_active` default is `False`, Notification field sizes match init.sql (title=500, notification_type=50, channel=50, reference_type=100)
- [ ] `backend/app/api/v1/brands.py` — `is_active = True` during activation; bidirectional is_active/status sync; "activating" counts as active
- [ ] `backend/app/scheduler/publish_checker.py` — status set to "publishing" BEFORE dispatch; on failure set to "failed"
- [ ] `agents/workflows/research/nodes.py` — 3 error returns have `"status": "failed"`; `identify_gaps` and `build_personas` wrapped in try/except
- [ ] `agents/workflows/research/graph.py` — ALL edges use `_check_failed` conditional routing
- [ ] `agents/workflows/strategy/graph.py` — ALL edges use `_check_failed` conditional routing
- [ ] `agents/workflows/planning/graph.py` — ALL edges use `_check_failed` conditional routing
- [ ] `agents/workflows/content/graph.py` — ALL edges use `_check_failed` conditional routing
- [ ] `agents/workflows/evaluation/graph.py` — ALL edges use `_check_failed` conditional routing
- [ ] `agents/workflows/adaptation/graph.py` — ALL edges use `_check_failed` conditional routing + has `_check_failed` function defined
- [ ] `agents/workflows/content/nodes.py` — adapt_platforms fallback is `["instagram"]` not ALL_CHANNELS
- [ ] `agents/shared/tools/database.py` — calendar IDs sorted by scheduled_at ASC with tz-aware comparison
- [ ] `agents/worker.py` — `current_depth` defined before sequential chaining block; `GraphInterrupt` imported and caught; chain depth uses `current_depth + 1 < MAX_CHAIN_DEPTH`
- [ ] `frontend/src/app/brands/[id]/page.tsx` — competitors check uses `competitors.length` (state variable); competitors fetched on initial page load

**v2 fixes to verify:**
- [ ] `backend/app/config.py` — Azure AD credentials validated in production startup
- [ ] `frontend/src/lib/auth.ts` — env var validation at module load
- [ ] `frontend/src/components/brand/BrandForm.tsx` — NO `is_active` field in form submission
- [ ] `db/init.sql` — agent_runs: brand_id is `NOT NULL` + `ON DELETE CASCADE`; prompt_version_id is `ON DELETE SET NULL`; initiated_by is `ON DELETE SET NULL`
- [ ] `agents/workflows/planning/nodes.py` — `load_strategy` parses JSON string; `generate_campaigns` and `generate_calendar` wrapped in try/except; `assign_products` has try/except on DB call
- [ ] `agents/workflows/research/nodes.py` — Qdrant `async_create_collection` wrapped in inner try/except
- [ ] `backend/app/services/content_service.py` — VALID_TRANSITIONS includes "publishing" state and "failed"→"scheduled" retry
- [ ] `agents/workflows/content/nodes.py` — product sourcing uses `product_ids` from calendar item; else block properly indented
- [ ] `agents/shared/image_processing.py` — logo width guard checks `logo.width > 0`; coordinate clipping uses `max(0, w - logo_w)`
- [ ] `backend/app/api/v1/files.py` — path traversal check blocks `..` and leading `/`
- [ ] `backend/app/api/v1/approvals.py` — accepts "rejected" status
- [ ] `backend/app/models/brand.py` — `bc_locations` typed as `Mapped[list]`
- [ ] `backend/app/models/product.py` — `image_urls` typed as `Mapped[list | None]`

---

### Section B: Authentication & Authorization

**Files:** `backend/app/auth/entra.py`, `backend/app/deps.py`, `backend/app/auth/models.py`, `backend/app/auth/permissions.py`, `backend/app/main.py`, `backend/app/config.py`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts`, `frontend/src/app/providers-wrapper.tsx`

- [ ] JWT validation: correct issuer, audience, algorithms
- [ ] CORS: locked to FRONTEND_URL, not wildcard
- [ ] Token refresh: expiresAt calculation correct (seconds not ms)
- [ ] Role hierarchy: admin(100) > manager(80) > editor(60) > viewer(10)
- [ ] All protected endpoints use `Depends(get_current_user)`
- [ ] Public endpoints: `/health`, `/api/v1/files/`, `/api/v1/webhooks/publish-result` — verify each is intentionally public
- [ ] `api.ts` Authorization header injection works correctly

---

### Section C: Brand Lifecycle

**Files:** `backend/app/models/brand.py`, `backend/app/schemas/brand.py`, `backend/app/api/v1/brands.py`, `backend/app/services/brand_service.py`, `frontend/src/app/brands/[id]/page.tsx`, `frontend/src/components/brand/BrandOnboarding.tsx`, `frontend/src/components/brand/BrandForm.tsx`

- [ ] New brands: status='onboarding', is_active=false
- [ ] complete-onboarding validates: name, description, tone_of_voice, >=1 logo, >=1 channel
- [ ] activate: status='activating', is_active=true, publishes research.trigger with trigger=activation, scope_weeks=2
- [ ] Deactivation cancels running agent_runs
- [ ] BrandForm does NOT send is_active field
- [ ] Onboarding progress uses API-fetched competitors state

---

### Section D: All 7 Workflow Graphs

**Files:** All `graph.py` files in `agents/workflows/research/`, `strategy/`, `planning/`, `content/`, `evaluation/`, `adaptation/`, `product_intel/`

- [ ] Every graph has a `_check_failed` function defined
- [ ] Every inter-node edge (except terminal → END) uses `add_conditional_edges` with `_check_failed`
- [ ] Entry points are set correctly
- [ ] Graphs that need checkpointers (strategy, adaptation) have them
- [ ] product_intel graph follows the same pattern

---

### Section E: Workflow Nodes — Error Handling

**Files:** All `nodes.py` files in every workflow

- [ ] Every node that calls `chat_completion()` is wrapped in try/except returning `{"status": "failed"}`
- [ ] Every node that calls database functions has error handling
- [ ] Every error return includes `"status": "failed"` for conditional edge routing
- [ ] No bare `return {"errors": [...]}` without status field
- [ ] LLM results are parsed with `parse_llm_json()` with fallback values

---

### Section F: Worker Pipeline

**Files:** `agents/worker.py`, `agents/shared/nats_consumer.py`

- [ ] All 7 NATS subjects subscribed
- [ ] `ack_wait` >= WORKFLOW_TIMEOUT
- [ ] `max_deliver=5`
- [ ] Idempotency check correct (brand+agent_type, running, 30 min window)
- [ ] Chain fires ONLY for trigger=activation
- [ ] Planning→content fan-out: sorts IDs, publishes first, passes remaining_queue
- [ ] Sequential content chaining: current_depth defined first, next item published, rest propagated
- [ ] Brand activation: status='active', is_active=true after planning completes
- [ ] GraphInterrupt caught and handled as paused_for_review
- [ ] Chain depth guard: `current_depth + 1 < MAX_CHAIN_DEPTH` (not `current_depth < MAX`)
- [ ] trigger, scope_weeks, chain_depth propagate through all chain messages
- [ ] msg.ack() called in all paths (success, failure, duplicate, timeout, interrupt)

---

### Section G: Publishing Pipeline

**Files:** `backend/app/scheduler/publish_checker.py`, `backend/app/services/publish_service.py`, `backend/app/api/v1/webhooks.py`, `backend/app/services/content_service.py`

- [ ] Publish checker: status='scheduled' AND scheduled_at <= NOW()
- [ ] Status set to "publishing" BEFORE dispatch
- [ ] On dispatch failure: status set to "failed" (not orphaned in "publishing")
- [ ] VALID_TRANSITIONS includes: scheduled→publishing, publishing→published, publishing→failed, failed→scheduled
- [ ] Webhook validates X-Webhook-Secret (returns 503 if unconfigured)
- [ ] On success: platform_post_id set, cal_item status='published', published_at set
- [ ] On failure: cal_item status='failed', error in generation_metadata
- [ ] website_blog: no dispatch, mark ready_to_publish
- [ ] teams: direct webhook, not n8n

---

### Section H: Content Generation Nodes

**Files:** `agents/workflows/content/nodes.py`, `agents/workflows/content/image_sourcing.py`, `agents/shared/image_processing.py`

- [ ] load_context: sets cal item status to 'working'
- [ ] source_product_image: uses product_ids from calendar item; NEVER AI-generates product photos
- [ ] generate_background: logo-safe composition prompt
- [ ] apply_branding: SVG→PNG, numpy variance placement, never bottom-left
- [ ] Logo dimension guards: width > 0 check, coordinate clipping prevents negatives
- [ ] adapt_platforms: fallback is ["instagram"], not ALL_CHANNELS
- [ ] store_content: status→'in_review', mockup_urls in generation_metadata

---

### Section I: Database Schema Integrity

**Files:** `db/init.sql`, all files in `backend/app/models/`, all files in `backend/app/schemas/`

- [ ] Every model field matches init.sql: name, type, size, nullable, default
- [ ] Brand status CHECK: onboarding, activating, active, inactive
- [ ] CalendarItem status CHECK: queued, working, in_review, reworking, approved, scheduled, publishing, published, failed
- [ ] agent_runs: brand_id NOT NULL, ON DELETE CASCADE; prompt_version_id ON DELETE SET NULL; initiated_by ON DELETE SET NULL
- [ ] Notification model: title String(500), notification_type String(50), channel String(50), reference_type String(100)
- [ ] Brand model: bc_locations Mapped[list], not Mapped[dict]
- [ ] Product model: image_urls Mapped[list | None], not Mapped[dict | None]
- [ ] All FK cascades appropriate (CASCADE for owned data, SET NULL for references)
- [ ] Indexes exist for: calendar_items(status), calendar_items(scheduled_at), agent_runs(brand_id, status), products(brand_id)

---

### Section J: Frontend Data Flow

**Files:** `frontend/src/lib/api.ts`, `frontend/src/types/index.ts`, key page files

- [ ] API_BASE_URL enforces HTTPS for non-localhost
- [ ] fileUrl() rewrites minio:9000 URLs correctly
- [ ] All .map() calls have Array.isArray() guards
- [ ] TypeScript interfaces in types/index.ts match backend Pydantic schemas for critical types (Brand, Content, CalendarItem, AgentRun)
- [ ] Every image/asset display uses fileUrl() for MinIO URLs
- [ ] Path traversal protection confirmed on files endpoint

---

### Section K: Infrastructure

**Files:** `docker-compose.yml`, `docker-compose.vps.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `agents/Dockerfile`

- [ ] Uvicorn: --proxy-headers --forwarded-allow-ips *
- [ ] Frontend Dockerfile: default ARG is HTTPS URL
- [ ] ODBC Driver 17 in backend + agents
- [ ] All healthchecks use curl
- [ ] VPS overlay: zero host port bindings
- [ ] No http:// in production config (except internal Docker hostnames)
- [ ] All containers run as non-root

---

### Section L: Scheduler & Daily Jobs

**Files:** `backend/app/scheduler/__init__.py`, `backend/app/scheduler/morning_jobs.py`, `backend/app/scheduler/publish_checker.py`

- [ ] get_app_setting() reads from DB
- [ ] Morning job order: BC sync → engagement → evaluation → content top-up
- [ ] Content top-up reads days_ahead from DB, finds nearest queued/planned item
- [ ] Job failures logged with duration_ms
- [ ] Scheduler started in main.py on correct lifecycle event

---

## Convergence Criteria

A pass is **clean** when ALL of the above checks pass and ZERO new findings are discovered. The audit is complete when one clean pass is achieved.

## Deliverables

After convergence:
1. Report the total number of passes required
2. List any fixes applied during v3 passes
3. Append v3 results to `AUDIT_RESULTS.md`
4. Update `DEPLOY_FIX.md` if any new migrations needed
5. Final statement: "CONVERGED after N passes — zero issues remaining"
