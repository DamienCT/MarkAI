# MARKAI Full Verification Audit — v5 Loop Prompt

**Purpose:** Comprehensive audit of every file in the MARKAI application, executed as an iterative loop. Every feature, workflow, endpoint, component, and model reference must be verified. The loop continues until zero findings remain.

**Total source files:** 220+ (82 backend, 46 agents, 84 frontend, 1 SQL, 6 Docker/config)

---

## Execution Protocol

```
LOOP:
  1. AUDIT    — Read every file, verify every checklist item
  2. REVIEW   — Compile all findings: bugs, mismatches, missing implementations
  3. PLAN     — For each finding, determine the exact fix (file, line, change)
  4. FIX      — Implement every fix
  5. TEST     — Verify each fix doesn't break adjacent code; check imports, types, logic
  6. RE-AUDIT — Re-read every modified file + its dependents, verify the fix is correct
  7. IF findings > 0 → GOTO 1
  8. IF findings == 0 → Write final AUDIT_RESULTS.md and EXIT
```

**Rules:**
- Do NOT skip files. Do NOT assume correctness. Read every line.
- Every fix must be verified by re-reading the file after editing.
- Track loop iteration count. Maximum 5 iterations (safety limit).
- Each iteration must produce a findings count. The count must decrease or stay at zero.

---

## Section 0: AI Model Settings — Zero Hardcoded Models

**This section is the highest priority. Every model reference in source code MUST be dynamically resolved from the database/settings. Nothing hardcoded.**

### Architecture

The model resolution chain is:
1. Admin selects models per category in UI (`/providers` page)
2. Selections stored in `ai_model_selections` table
3. Backend resolves via `get_active_model(category_slug)` in `ai_model_service.py`
4. Agents resolve via `get_model_for_category(category)` in `agents/shared/llm.py`
5. LiteLLM proxy routes the model name to the actual provider

### Required Model Categories

Only these categories should exist. Remove any others (tts, stt, video, moderation) unless actively used in a workflow:

| Category Slug | Purpose | Used By | Required |
|--------------|---------|---------|----------|
| `text` | Primary LLM for all agent workflows | All workflow nodes, strategy, planning, content | YES |
| `text-fast` | Lightweight LLM for quick tasks | Intelligence API, competitor descriptions | YES |
| `image` | Image generation | Content workflow background generation | YES |
| `embedding` | Vector embeddings | Research workflow Qdrant storage | YES |
| `vision` | Multimodal vision analysis | Product image analysis (if used) | ONLY if used |

### Files to read:

- `backend/app/services/ai_model_service.py` — full file
- `backend/app/models/ai_model.py` — full file
- `backend/app/api/v1/providers.py` — full file
- `backend/app/api/v1/intelligence.py` — full file
- `backend/app/services/gemini_service.py` — full file
- `agents/shared/llm.py` — full file
- `agents/shared/config.py` — full file
- `agents/workflows/content/nodes.py` — image generation calls
- `agents/workflows/content/image_sourcing.py` — image sourcing calls
- `agents/workflows/research/nodes.py` — all chat_completion calls
- `agents/workflows/strategy/nodes.py` — all chat_completion calls
- `agents/workflows/planning/nodes.py` — all chat_completion calls
- `agents/workflows/evaluation/nodes.py` — all chat_completion calls
- `agents/workflows/adaptation/nodes.py` — all chat_completion calls
- `agents/workflows/product_intel/nodes.py` — all chat_completion calls
- `frontend/src/app/providers/page.tsx` — model management UI
- `frontend/src/app/settings/page.tsx` — settings UI
- `db/init.sql` — ai_model_categories, ai_models, ai_model_selections tables
- `litellm/config.yaml` — proxy routing
- `review/generate_posts.py` — test script (if exists)

### Verify — Zero Hardcoded Models:

- [ ] `intelligence.py`: `_call_llm()` MUST resolve model from `get_active_model("text-fast")` — NOT hardcoded `gpt-5.4-mini`
- [ ] `intelligence.py`: LiteLLM fallback MUST also use dynamic model name — NOT hardcoded `openai/gpt-5.4-mini`
- [ ] `gemini_service.py`: Image model names MUST come from settings or `get_active_model("image")` — NOT hardcoded list
- [ ] `content/nodes.py`: ANY direct Gemini API calls MUST use settings-resolved model — NOT hardcoded `gemini-2.5-flash-image`
- [ ] `agents/shared/llm.py`: `chat_completion()` MUST call `get_model_for_category()` — verify the resolution chain
- [ ] `agents/shared/llm.py`: `get_embedding()` MUST use `get_model_for_category("embedding")` — NOT hardcoded
- [ ] `agents/shared/llm.py`: Image generation MUST use `get_model_for_category("image")` — NOT hardcoded
- [ ] Fallback defaults in `ai_model_service.py` and `agents/shared/llm.py` MUST be identical and MUST only be used when DB has no selection
- [ ] `grep -r` entire codebase for patterns: `"gpt-5.4"`, `"gpt-5.4-mini"`, `"gpt-image"`, `"text-embedding"`, `"gemini-"`, `"dall-e"`, `"whisper"`, `"tts-1"`, `"sora"`, `"omni-moderation"` in `.py`, `.ts`, `.tsx` files (excluding `node_modules/`, `docs/`, `.md` files, comments) — ZERO matches allowed in executable code outside of fallback defaults
- [ ] `litellm/config.yaml`: This is configuration (acceptable), but model names MUST match what the UI can discover and select

### Verify — Model Selection Completeness:

- [ ] `db/init.sql`: `ai_model_categories` table has seed data for ALL required categories
- [ ] `db/init.sql`: `ai_model_selections` table has DEFAULT selections for ALL required categories — so brands can activate immediately after fresh deploy
- [ ] `get_active_model()`: Returns a usable model for EVERY required category even on fresh DB (fallback chain works)
- [ ] Brand activation does NOT fail due to missing model selections — trace the activation flow and verify no model resolution returns None/empty that would block the pipeline
- [ ] Frontend `/providers` page: Shows ALL required categories, allows selection, validates that each has an active model
- [ ] Frontend `/providers` page: Shows clear warning if any required category has no model selected

### Verify — Unused Categories Removed:

- [ ] If `tts`, `stt`, `video`, `moderation` categories are NOT used in any workflow, remove them from: seed data, fallback defaults, discovery filters, and frontend display
- [ ] If `vision` category is not actively used in any workflow node, remove it or merge with `text`
- [ ] `ai_model_service.py` category definitions: Only list categories that have active consumers in the codebase

---

## Section 1: Authentication & Authorization

**Files to read (every line):**
- `backend/app/auth/entra.py`
- `backend/app/deps.py`
- `backend/app/auth/models.py`
- `backend/app/auth/permissions.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/app/providers-wrapper.tsx`
- `frontend/src/app/api/auth/[...nextauth]/route.ts`
- `frontend/src/types/next-auth.d.ts`

**Verify:**
- [ ] JWT validation: correct issuer, audience, algorithms (RS256)
- [ ] JWKS key rotation handled gracefully
- [ ] Security group check: JWT claim first, Graph API fallback
- [ ] New users auto-provisioned: security group -> admin + is_active=True; others -> viewer + is_active=False
- [ ] User model `is_active` default is `False` (model AND init.sql AND schema)
- [ ] Token refresh: expiresAt in seconds, REFRESH_BUFFER_SECONDS adequate
- [ ] `role_has_access` hierarchy: admin(100) > manager(80) > editor(60) > viewer(10)
- [ ] All protected endpoints use `Depends(get_current_user)` — grep every router file
- [ ] Intentionally public endpoints ONLY: `/health` (simple), `/api/v1/files/{path}`, `/api/v1/webhooks/publish-result`
- [ ] `/api/v1/system/health` (detailed) REQUIRES auth — exposes infrastructure status
- [ ] CORS locked to `FRONTEND_URL`, not wildcard
- [ ] Azure AD credentials validated in production startup (`config.py`)
- [ ] Frontend env var validation at module load (`auth.ts`)
- [ ] Session includes `accessToken` for API calls
- [ ] `api.ts` Authorization header injection correct
- [ ] Path traversal protection on `/api/v1/files/` (blocks `..` and leading `/`)
- [ ] Webhook secret: returns 503 when unconfigured, uses `secrets.compare_digest`
- [ ] No legacy model references (gpt-4o, gpt-3.5, gpt-4-turbo) anywhere in source code

---

## Section 2: Brand Lifecycle

**Files to read:**
- `backend/app/models/brand.py`
- `backend/app/schemas/brand.py`
- `backend/app/api/v1/brands.py`
- `backend/app/services/brand_service.py`
- `backend/app/api/v1/products.py`
- `backend/app/services/product_service.py`
- `db/init.sql` (brands + products tables)
- `frontend/src/app/brands/page.tsx`
- `frontend/src/app/brands/new/page.tsx`
- `frontend/src/app/brands/[id]/page.tsx`
- `frontend/src/components/brand/BrandOnboarding.tsx`
- `frontend/src/components/brand/BrandCard.tsx`
- `frontend/src/components/brand/BrandForm.tsx`
- `frontend/src/components/brand/WorkflowStatus.tsx`
- `frontend/src/components/brand/CompetitorTracker.tsx`
- `frontend/src/components/brand/tabs/OverviewTab.tsx`
- `frontend/src/components/brand/tabs/ChannelsTab.tsx`
- `frontend/src/components/brand/tabs/LogosTab.tsx`
- `frontend/src/components/brand/tabs/CompetitorsTab.tsx`
- `frontend/src/components/brand/tabs/EditBrandTab.tsx`
- `frontend/src/components/brand/tabs/ProductsTab.tsx`
- `frontend/src/components/brand/tabs/IntelligenceTab.tsx`
- `frontend/src/components/brand/tabs/PerformanceTab.tsx`

**Verify:**
- [ ] New brands: status='onboarding', is_active=false
- [ ] BrandCreate schema defaults match init.sql
- [ ] complete-onboarding validates: name, description, tone_of_voice, >=1 logo, >=1 enabled channel
- [ ] activate: status='activating', is_active=true, publishes research.trigger with trigger=activation, scope_weeks=2
- [ ] Activation does NOT fail due to missing model selections — verify the entire chain from NATS publish to first chat_completion resolves a model
- [ ] Bidirectional is_active/status sync on updates; "activating" counts as active
- [ ] Deactivating cancels running agent_runs
- [ ] BrandForm does NOT send `is_active` field
- [ ] Onboarding progress uses API-fetched `competitors` state (not `brand.competitors`)
- [ ] Competitors fetched on initial page load (not just when Intelligence tab opens)
- [ ] `bc_locations` typed as `Mapped[list]` (not dict)
- [ ] `brand_guidelines` JSON properly serialized/deserialized
- [ ] Brand deletion cascades correctly (all FK tables)
- [ ] agent_runs: brand_id NOT NULL, ON DELETE CASCADE

---

## Section 3: Research Workflow

**Files to read:**
- `agents/workflows/research/graph.py`
- `agents/workflows/research/nodes.py`
- `agents/workflows/research/state.py`
- `agents/shared/tools/database.py` (store_competitors, store_research, get_brand, get_brand_config, execute_query, build_brand_intelligence)
- `agents/shared/tools/vector.py`
- `agents/shared/tools/web_search.py`
- `agents/shared/tools/browser.py`
- `agents/shared/tools/social.py`
- `agents/shared/llm.py`
- `agents/shared/sanitize.py`

**Verify:**
- [ ] Graph has `_check_failed` + conditional edges on ALL nodes INCLUDING the final node
- [ ] `crawl_website`: loads website_url + extra URLs from brand_guidelines; returns status:"failed" if zero pages crawled
- [ ] `analyze_social`: enriched prompt requests engagement_rate, benchmark, peak_times, hashtag_analysis, recommendations
- [ ] `analyze_competitors`: enriched prompt requests positioning, strengths(3+), weaknesses(3+), social_presence, content_strategy, threat_level
- [ ] `analyze_competitors`: loads EXISTING DB competitors first, deduplicates by name
- [ ] `analyze_competitors`: return includes explicit `status` field
- [ ] `analyze_competitors`: ALL chat_completion calls (including competitor description) have try/except with logging
- [ ] `identify_gaps`: enriched prompt requests title, category, estimated_impact, implementation_effort, timeline, target_audience, success_metrics
- [ ] `build_personas`: enriched prompt requests demographics(object), content_preferences(object with formats/topics/tone/language_mix), buying_triggers, best_engagement_times, content_avoidance
- [ ] `store_results`: saves to agent_runs + Qdrant (non-fatal if Qdrant fails)
- [ ] Qdrant `async_create_collection` wrapped in inner try/except (race condition)
- [ ] ALL nodes with chat_completion() wrapped in try/except returning status:"failed"
- [ ] ALL error returns include `"status": "failed"` for conditional edge routing
- [ ] ALL chat_completion() calls use dynamic model resolution — NOT hardcoded model names
- [ ] `chat_completion()` uses retry with exponential backoff (3 attempts)
- [ ] `web_search()` uses DuckDuckGo, returns SearchResult objects
- [ ] `crawl_site()` falls back to direct HTTP when browser-worker is down

---

## Section 4: Strategy Workflow

**Files to read:**
- `agents/workflows/strategy/graph.py`
- `agents/workflows/strategy/nodes.py`
- `agents/workflows/strategy/state.py`

**Verify:**
- [ ] Graph has `_check_failed` + conditional edges on ALL nodes INCLUDING the final node
- [ ] MemorySaver checkpointer configured
- [ ] `load_research`: finds latest completed research, returns output_payload
- [ ] `generate_positioning`: enriched — includes brand_archetype, emotional_territory, competitive_differentiation
- [ ] `define_pillars`: enriched — includes audience_alignment, seasonal_emphasis, platform_fit, visual_style, pillar_rationale
- [ ] `define_audiences`: cross-references research personas explicitly; prompt includes personas as "source of truth"; output has persona_ref field
- [ ] `plan_cadence`: includes content_format_mix (% reels, carousels, stories, static)
- [ ] `generate_themes`: generates 12 months (not 3); includes sub_themes (4 weekly), key_dates with content_angle/format/audience, pillar_rotation; max_tokens=8192
- [ ] `human_review`: auto-approves for activation triggers; interrupts for manual
- [ ] ALL nodes with chat_completion() wrapped in try/except
- [ ] ALL chat_completion() calls use dynamic model resolution

---

## Section 5: Planning Workflow

**Files to read:**
- `agents/workflows/planning/graph.py`
- `agents/workflows/planning/nodes.py`
- `agents/workflows/planning/state.py`

**Verify:**
- [ ] Graph has `_check_failed` + conditional edges on ALL nodes INCLUDING the final node
- [ ] `load_strategy`: parses JSON string from output_payload; loads enabled_channels with fallback to ["instagram"]; loads existing_items for dedup
- [ ] `generate_campaigns`: enriched — requests target_metrics, creative_direction, content_format_mix, target_audience; passes products
- [ ] Strategy document: max_tokens=16384; cadence/audiences/pillars truncation >= 3000 chars each
- [ ] `generate_calendar`: enriched items include pillar, theme, weekly_sub_theme, target_audience, content_brief, visual_direction, cta_type
- [ ] `generate_calendar`: includes existing items as dedup context ("do NOT duplicate")
- [ ] `generate_calendar`: max_tokens=16384
- [ ] `generate_calendar`: enforces 1 post per enabled channel per day
- [ ] `assign_products`: has outer try/except wrapping entire function; matches real products from DB
- [ ] `store_calendar`: passes ALL new fields (pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type) to store_calendar_items()
- [ ] `store_calendar_items()` INSERT includes all 7 new columns
- [ ] Returns calendar_item_ids sorted by scheduled_at ASC (tz-aware)
- [ ] ALL chat_completion() calls use dynamic model resolution

---

## Section 6: Content Generation Workflow

**Files to read:**
- `agents/workflows/content/graph.py`
- `agents/workflows/content/nodes.py`
- `agents/workflows/content/state.py`
- `agents/workflows/content/image_sourcing.py`
- `agents/shared/image_processing.py`
- `agents/shared/tools/storage.py`

**Verify:**
- [ ] Graph has `_check_failed` + conditional edges on ALL nodes INCLUDING the final node
- [ ] `load_context`: calls `build_brand_intelligence()`; returns enriched state with positioning, relevant_pillar, relevant_audience, month_context, recent_posts, top_performing, product
- [ ] `load_context`: sets calendar item status to 'working'
- [ ] `_extract_month_section()`: extracts current month section from strategy document
- [ ] `_find_product()`: matches product by product_ids first, then fuzzy name
- [ ] `generate_hook`: enriched — includes brand archetype, pillar, audience pain points + tone, product, recent hooks to avoid, top performing hooks; max_tokens=256
- [ ] `generate_caption`: enriched — includes full positioning (NOT truncated to 2000), pillar description, audience preferences + language_mix, product details, month_context (5000 chars), recent captions to avoid, top performing, CTA with brand URL; max_tokens=2048
- [ ] `generate_hashtags`: full caption (NOT truncated to 500 chars); platform-specific limits; branded hashtag always included; max_tokens=512
- [ ] `source_product_image`: uses product_ids from calendar item; NEVER AI-generates product photos
- [ ] `generate_background`: includes brand color palette (hex), visual_style, audience aesthetic, seasonal direction
- [ ] `generate_background`: uses `get_model_for_category("image")` — NOT hardcoded model name
- [ ] ANY Gemini API calls use settings-resolved model — NOT hardcoded `gemini-*` string
- [ ] `apply_branding`: SVG->PNG, numpy variance placement, never bottom-left; logo width>0 guard; coordinate clipping prevents negatives
- [ ] `adapt_platforms`: enriched — includes positioning, brand voice, key messages, audience, brand URL; fallback is ["instagram"]
- [ ] `generate_mockups`: creates IG/FB/LI/X previews
- [ ] `store_content`: sets calendar item to 'in_review', stores mockup_urls in generation_metadata
- [ ] ALL nodes with chat_completion() wrapped in try/except
- [ ] ALL chat_completion() and image generation calls use dynamic model resolution

---

## Section 7: Worker Pipeline Orchestration

**Files to read:**
- `agents/worker.py`
- `agents/shared/nats_consumer.py`
- `agents/shared/config.py`
- `agents/shared/state.py`

**Verify:**
- [ ] All 7 NATS subjects subscribed: research, strategy, content, evaluation, product, planning, adaptation
- [ ] `ack_wait` >= WORKFLOW_TIMEOUT (1860s vs 1800s)
- [ ] `max_deliver=5`
- [ ] Idempotency: skips if same brand+agent_type running within 30 min
- [ ] Chain fires ONLY for trigger=activation
- [ ] Planning->content fan-out: sorts by scheduled_at, publishes FIRST item, passes remaining_queue
- [ ] Sequential content chaining: current_depth defined BEFORE chaining block
- [ ] After planning with trigger=activation: brand set to status='active', is_active=true
- [ ] `GraphInterrupt` imported from `langgraph.errors` and caught -> saves as paused_for_review
- [ ] Chain depth: `current_depth + 1 < MAX_CHAIN_DEPTH` (not `current_depth < MAX`)
- [ ] trigger, scope_weeks, chain_depth propagate through all chain messages
- [ ] msg.ack() called in ALL paths (success, failure, duplicate, timeout, interrupt)
- [ ] Evaluation always chains to adaptation regardless of trigger
- [ ] Product intel conditional chain to strategy

---

## Section 8: Publishing Pipeline

**Files to read:**
- `backend/app/scheduler/publish_checker.py`
- `backend/app/services/publish_service.py`
- `backend/app/api/v1/webhooks.py`
- `backend/app/services/content_service.py`
- `backend/app/models/content.py`
- `backend/app/models/calendar_item.py`
- `backend/app/schemas/content.py`

**Verify:**
- [ ] Publish checker: status='scheduled' AND scheduled_at <= NOW()
- [ ] Status set to "publishing" BEFORE dispatch
- [ ] On dispatch failure: status set to "failed" (not orphaned in "publishing")
- [ ] `VALID_TRANSITIONS` includes: scheduled->publishing, publishing->published, publishing->failed, failed->scheduled
- [ ] `dispatch_to_n8n` sends to unified `/markai/publish` endpoint
- [ ] Payload includes channel-specific credentials from brand_guidelines
- [ ] website_blog: no dispatch, mark ready_to_publish
- [ ] teams: direct Teams webhook, not n8n
- [ ] Webhook validates X-Webhook-Secret (503 if unconfigured)
- [ ] On success: platform_post_id, status='published', published_at
- [ ] On failure: status='failed', error in generation_metadata
- [ ] Content model: `image_urls` typed as `Mapped[list | None]` (NOT dict)
- [ ] CalendarItem model: has all 7 new columns (pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type)

---

## Section 9: Engagement Tracking & Evaluation

**Files to read:**
- `backend/app/scheduler/engagement_puller.py`
- `backend/app/services/engagement_service.py`
- `backend/app/models/engagement.py`
- `agents/workflows/evaluation/graph.py`
- `agents/workflows/evaluation/nodes.py`
- `agents/workflows/evaluation/state.py`

**Verify:**
- [ ] Engagement pull: fetches from Instagram/Facebook/LinkedIn APIs
- [ ] Uses per-channel credentials from brand_guidelines
- [ ] Only pulls for status='published' items
- [ ] Evaluation graph: `_check_failed` + conditional edges on ALL nodes INCLUDING final node
- [ ] ALL evaluation nodes (including store_adaptations_node) wrapped in try/except
- [ ] Evaluation loads 30-day performance data
- [ ] Recommendations classified into tier 1/2/3
- [ ] ALL chat_completion() calls use dynamic model resolution

---

## Section 10: Adaptation Workflow

**Files to read:**
- `agents/workflows/adaptation/graph.py`
- `agents/workflows/adaptation/nodes.py`
- `agents/workflows/adaptation/state.py`
- `backend/app/models/adaptation.py`
- `backend/app/schemas/adaptation.py`

**Verify:**
- [ ] Adaptation graph: has `_check_failed` + conditional edges on ALL nodes INCLUDING final node
- [ ] MemorySaver checkpointer configured
- [ ] Tier 1 auto-applied; tier 2/3 require human interrupt via `interrupt()`
- [ ] Adaptation->planning feedback loop: `current_depth + 1 < MAX_CHAIN_DEPTH`
- [ ] `adapted_headline` field: String(500) matching init.sql VARCHAR(500)

---

## Section 11: Product Intelligence Workflow

**Files to read:**
- `agents/workflows/product_intel/graph.py`
- `agents/workflows/product_intel/nodes.py`
- `agents/workflows/product_intel/state.py`
- `agents/shared/tools/image_search.py`

**Verify:**
- [ ] Graph has `_check_failed` + conditional edges on ALL nodes INCLUDING final node
- [ ] ALL nodes with chat_completion() wrapped in try/except returning status:"failed" (including research_brand)
- [ ] Product images: prioritizes BC > supplier > web search; NO AI-generated images
- [ ] Worker chains product_intel -> strategy (conditional on existing research)
- [ ] ALL chat_completion() calls use dynamic model resolution

---

## Section 12: Scheduler & Daily Jobs

**Files to read:**
- `backend/app/scheduler/__init__.py`
- `backend/app/scheduler/morning_jobs.py`
- `backend/app/scheduler/bc_sync.py`
- `backend/app/scheduler/model_discovery.py`
- `backend/app/scheduler/publish_checker.py`

**Verify:**
- [ ] `get_app_setting()` reads from DB app_settings table
- [ ] Morning job order: BC sync -> engagement pull -> evaluation trigger -> content top-up
- [ ] Content top-up: uses status='queued' only (NOT 'planned')
- [ ] Content top-up: finds nearest item within days_ahead window
- [ ] All job failures logged to scheduled_job_log with duration_ms
- [ ] Scheduler started correctly in main.py lifespan

---

## Section 13: All API Endpoints

**Files to read (every router):**
- `backend/app/api/router.py`
- `backend/app/api/v1/agents.py`
- `backend/app/api/v1/analytics.py`
- `backend/app/api/v1/approvals.py`
- `backend/app/api/v1/brands.py`
- `backend/app/api/v1/calendar.py`
- `backend/app/api/v1/campaigns.py`
- `backend/app/api/v1/content.py`
- `backend/app/api/v1/dashboard.py`
- `backend/app/api/v1/files.py`
- `backend/app/api/v1/intelligence.py`
- `backend/app/api/v1/learning.py`
- `backend/app/api/v1/notifications.py`
- `backend/app/api/v1/products.py`
- `backend/app/api/v1/prompts.py`
- `backend/app/api/v1/providers.py`
- `backend/app/api/v1/settings.py`
- `backend/app/api/v1/system.py`
- `backend/app/api/v1/users.py`
- `backend/app/api/v1/webhooks.py`

**Verify:**
- [ ] Every router registered with correct prefix in router.py
- [ ] Correct HTTP methods (GET reads, POST creates, PUT/PATCH updates, DELETE deletes)
- [ ] files.py: path traversal protection blocks `..` and leading `/`
- [ ] approvals.py: accepts "approved", "rejected", "revision_requested"
- [ ] intelligence.py: uses dynamically resolved model — NOT hardcoded model name
- [ ] All endpoints needing auth use `Depends(get_current_user)`
- [ ] system.py `/health` (detailed) requires auth
- [ ] users.py: only admins can manage users
- [ ] providers.py: active models endpoint returns all required categories

---

## Section 14: All Services

**Files to read:**
- `backend/app/services/ai_model_service.py`
- `backend/app/services/analytics_service.py`
- `backend/app/services/approval_service.py`
- `backend/app/services/brand_service.py`
- `backend/app/services/calendar_service.py`
- `backend/app/services/content_service.py`
- `backend/app/services/engagement_service.py`
- `backend/app/services/fabric_service.py`
- `backend/app/services/gemini_service.py`
- `backend/app/services/minio_service.py`
- `backend/app/services/nats_service.py`
- `backend/app/services/notification_service.py`
- `backend/app/services/product_service.py`
- `backend/app/services/prompt_service.py`
- `backend/app/services/publish_service.py`
- `backend/app/services/qdrant_service.py`

**Verify:**
- [ ] `content_service.py` VALID_TRANSITIONS: includes publishing state; failed->scheduled for retry
- [ ] `ai_model_service.py`: `get_active_model()` has MINIMAL fallback defaults (only for required categories)
- [ ] `ai_model_service.py`: fallback defaults match `agents/shared/llm.py` fallback defaults EXACTLY
- [ ] `ai_model_service.py`: unused categories (tts, stt, video, moderation) removed from fallback defaults if not used
- [ ] `gemini_service.py`: model names resolved from settings — NOT hardcoded
- [ ] `nats_service.py`: publish function works correctly
- [ ] `publish_service.py`: Teams = direct webhook; website_blog = ready_to_publish; others = n8n
- [ ] `engagement_service.py`: uses Meta Graph API v20+, LinkedIn API v2
- [ ] `fabric_service.py`: BC sync via Microsoft Fabric SQL with Azure AD auth
- [ ] All services: proper async/await, no blocking calls in async functions
- [ ] All services: DB sessions committed/rolled back properly

---

## Section 15: Database Schema Integrity

**Files to read:**
- `db/init.sql` (entire file)
- All files in `backend/app/models/`
- All files in `backend/app/schemas/`

**Verify:**
- [ ] Every model field matches init.sql: name, type, size, nullable, default
- [ ] Brand status CHECK: onboarding, activating, active, inactive
- [ ] CalendarItem status CHECK: queued, working, in_review, reworking, approved, scheduled, publishing, published, failed
- [ ] CalendarItem has columns: pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type
- [ ] CalendarItem indexes: pillar, theme, brand_id+scheduled_at
- [ ] users.is_active DEFAULT FALSE (init.sql AND model AND schema)
- [ ] agent_runs: brand_id NOT NULL ON DELETE CASCADE; prompt_version_id ON DELETE SET NULL; initiated_by ON DELETE SET NULL
- [ ] Notification model: title String(500), notification_type String(50), channel String(50), reference_type String(100)
- [ ] Brand: bc_locations Mapped[list]; Product: image_urls Mapped[list|None]
- [ ] Content: image_urls Mapped[list|None] (NOT dict)
- [ ] Adaptation: adapted_headline String(500) (NOT 255)
- [ ] PromptVersion: category String(100) (NOT 255)
- [ ] agent_run model: brand_id Mapped[uuid.UUID] (NOT Optional), nullable=False
- [ ] agent_run schema: brand_id uuid.UUID (NOT Optional)
- [ ] All FK cascades appropriate (CASCADE for owned data, SET NULL for references)
- [ ] app_settings has content_generation_days_ahead row
- [ ] ai_model_categories has seed rows for ALL required categories
- [ ] ai_model_selections has default selections for ALL required categories

---

## Section 16: All Frontend Pages & Components

**Files to read (every page):**
- `frontend/src/app/page.tsx` (Dashboard)
- `frontend/src/app/brands/page.tsx`
- `frontend/src/app/brands/new/page.tsx`
- `frontend/src/app/brands/[id]/page.tsx`
- `frontend/src/app/content/page.tsx`
- `frontend/src/app/content/[id]/page.tsx`
- `frontend/src/app/content/calendar/page.tsx`
- `frontend/src/app/approvals/page.tsx`
- `frontend/src/app/intelligence/page.tsx`
- `frontend/src/app/intelligence/products/page.tsx`
- `frontend/src/app/intelligence/report/[id]/page.tsx`
- `frontend/src/app/analytics/page.tsx`
- `frontend/src/app/learning/page.tsx`
- `frontend/src/app/prompts/page.tsx`
- `frontend/src/app/providers/page.tsx`
- `frontend/src/app/settings/page.tsx`
- `frontend/src/app/settings/users/page.tsx`
- `frontend/src/app/system/page.tsx`
- `frontend/src/app/system/audit/page.tsx`
- `frontend/src/app/auth/signin/page.tsx`
- `frontend/src/app/error.tsx`
- `frontend/src/app/layout.tsx`

**Components to read:**
- `frontend/src/components/content/CalendarView.tsx`
- `frontend/src/components/content/ContentCard.tsx`
- `frontend/src/components/content/ContentEditor.tsx`
- `frontend/src/components/content/KanbanBoard.tsx`
- `frontend/src/components/content/PlatformMockups.tsx`
- `frontend/src/components/content/AssetPreview.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/components/layout/Header.tsx`
- `frontend/src/components/layout/BrandSwitcher.tsx`
- `frontend/src/components/approval/ApprovalActions.tsx`
- `frontend/src/components/approval/ApprovalHistory.tsx`
- `frontend/src/components/analytics/EngagementChart.tsx`
- `frontend/src/components/analytics/PerformanceGrid.tsx`
- `frontend/src/components/analytics/PostingHeatmap.tsx`
- `frontend/src/components/system/ServiceHealth.tsx`
- `frontend/src/components/system/QueueDepth.tsx`
- `frontend/src/components/system/WorkflowMonitor.tsx`

**Shared:**
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/hooks.ts`
- `frontend/src/lib/utils.ts`
- `frontend/src/types/index.ts`
- `frontend/src/types/next-auth.d.ts`

**Verify:**
- [ ] API_BASE_URL enforces HTTPS for non-localhost
- [ ] `fileUrl()` rewrites minio:9000 URLs to backend proxy
- [ ] All `.map()` calls have `Array.isArray()` guards
- [ ] `types/index.ts`: CalendarItem has pillar, theme, target_audience, content_brief
- [ ] `types/index.ts`: ContentStatus includes "publishing"
- [ ] Report detail page renders enriched fields: competitor threat_level, gap impact/effort, persona content_preferences, positioning brand_archetype, pillar audience_alignment
- [ ] CalendarView shows pillar badge + target_audience badge on items
- [ ] KanbanBoard shows pillar badge + target_audience badge on cards
- [ ] KanbanBoard has "publishing" column between "scheduled" and "published"
- [ ] KanbanBoard Row 2 grid is 5 columns (not 4)
- [ ] `statusColor()` includes "publishing" with violet color
- [ ] Sidebar navigation links match actual routes
- [ ] Kanban columns match ALL valid status values (9 statuses)
- [ ] Every image uses `fileUrl()` for MinIO URLs
- [ ] Settings page includes content_generation_days_ahead slider
- [ ] Providers page shows all required model categories with active selections

---

## Section 17: Infrastructure & Configuration

**Files to read:**
- `docker-compose.yml`
- `docker-compose.override.yml`
- `docker-compose.vps.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `agents/Dockerfile`
- `litellm/config.yaml`
- `eval/promptfooconfig.yaml`

**Verify:**
- [ ] Uvicorn: `--proxy-headers --forwarded-allow-ips *`
- [ ] Frontend Dockerfile default ARG is HTTPS production URL
- [ ] ODBC Driver 17 in backend + agents
- [ ] All healthchecks use curl (not wget)
- [ ] VPS overlay: zero host port bindings, external Traefik network
- [ ] No http:// in production config (except internal Docker hostnames)
- [ ] All containers run as non-root
- [ ] LiteLLM config: model list matches what the DB can discover and select
- [ ] LiteLLM config: no legacy models (gpt-4o, gpt-3.5, dall-e-3)
- [ ] Eval config: uses dynamically resolved model or current active model

---

## Section 18: BrandIntelligence & Cross-Component Data Flow

**Files to read:**
- `agents/shared/tools/database.py` — `build_brand_intelligence()`, `get_recent_calendar_items()`, `_parse_payload()`
- `agents/workflows/content/nodes.py` — `load_context()`, `_extract_month_section()`, `_find_product()`
- `agents/workflows/planning/nodes.py` — `load_strategy()`, existing_items dedup

**Verify:**
- [ ] `build_brand_intelligence()` loads: brand config, products, research, strategy, planning, strategy_document, recent_posts (90 days), top_performing (10 items)
- [ ] `_parse_payload()` handles string, dict, and None correctly
- [ ] `get_recent_calendar_items()` queries with proper date interval and limit
- [ ] Content `load_context()` calls `build_brand_intelligence()` and returns enriched state
- [ ] `_extract_month_section()` extracts correct month from strategy document
- [ ] `_find_product()` matches by product_ids first, then fuzzy name
- [ ] `relevant_pillar` matched from strategy pillars by pillar name
- [ ] `relevant_audience` matched from research personas by name
- [ ] Dedup: recent_posts injected into hook/caption prompts as "do NOT repeat"
- [ ] Learning: top_performing injected into hook/caption prompts as "learn from these"
- [ ] Research personas flow into strategy audiences (persona_ref cross-reference)
- [ ] Strategy themes flow into planning calendar (pillar_rotation, weekly sub-themes)
- [ ] Strategy document flows into content generation (month_context excerpt)
- [ ] Brand colors from brand_guidelines flow into image generation prompts

---

## Section 19: Agents Shared Utilities

**Files to read:**
- `agents/shared/config.py`
- `agents/shared/llm.py`
- `agents/shared/image_processing.py`
- `agents/shared/nats_consumer.py`
- `agents/shared/sanitize.py`
- `agents/shared/state.py`
- `agents/shared/tools/browser.py`
- `agents/shared/tools/database.py`
- `agents/shared/tools/fabric.py`
- `agents/shared/tools/image_search.py`
- `agents/shared/tools/social.py`
- `agents/shared/tools/storage.py`
- `agents/shared/tools/vector.py`
- `agents/shared/tools/web_search.py`

**Verify:**
- [ ] `llm.py`: `get_model_for_category()` calls backend API to resolve model dynamically
- [ ] `llm.py`: fallback defaults are MINIMAL (only required categories) and match `ai_model_service.py` exactly
- [ ] `llm.py`: `chat_completion()` resolves model via `get_model_for_category("text")` — NOT hardcoded
- [ ] `llm.py`: `get_embedding()` resolves model via `get_model_for_category("embedding")` — NOT hardcoded
- [ ] `llm.py`: retry 3 attempts with exponential backoff
- [ ] `llm.py`: max_tokens default 4096
- [ ] `image_processing.py`: logo placement never bottom-left; width>0 guard; coordinate clipping with max(0,...)
- [ ] `sanitize.py`: HTML sanitization applied to LLM outputs (not just inputs)
- [ ] `storage.py`: MinIO upload sets correct content-type; returns accessible URLs
- [ ] `social.py`: Instagram/Facebook/LinkedIn API calls with proper auth
- [ ] `browser.py`: crawl_site with timeout, fallback to direct HTTP
- [ ] `web_search.py`: DuckDuckGo HTML endpoint, no API key required
- [ ] `vector.py`: Qdrant operations with 1536-dimension vectors (or dynamically from embedding model)
- [ ] `database.py`: all functions use parameterized queries (no SQL injection)
- [ ] `fabric.py`: Microsoft Fabric SQL with Azure AD token auth

---

## Deliverables

After completing ALL loop iterations:
1. **Fix every bug found** — implement all fixes directly
2. **Update `AUDIT_RESULTS.md`** — replace with final findings (include iteration count and per-iteration findings)
3. **Update `DEPLOY_FIX.md`** if any new deployment steps needed
4. **End-to-end pipeline trace** — mentally walk through brand activation -> research -> strategy -> planning -> content for a single post, verifying every field propagates correctly AND every model resolution succeeds
5. **Model resolution trace** — trace from UI model selection -> DB -> `get_active_model()` -> `get_model_for_category()` -> `chat_completion()` -> LiteLLM proxy -> OpenAI API, verifying zero hardcoded values in the chain
