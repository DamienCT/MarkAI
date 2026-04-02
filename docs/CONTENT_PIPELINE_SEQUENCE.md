# MarkAI Content Pipeline — Sequence Map

> This document describes the complete flow from brand onboarding to published post.
> Use this as a reference when maintaining or extending the system.

---

## Overview

```
Brand Onboarding → Activation → Research → Strategy → Planning → Content Generation → Approval → Publishing
```

---

## Phase 1: Brand Onboarding

**UI:** `/brands/new` → BrandForm → BrandOnboarding (8 steps)

| Step | What happens | Where |
|------|-------------|-------|
| 1. Basic Info | Name, description, website URL, tone of voice | `frontend/src/components/brand/BrandForm.tsx` |
| 2. Business Central | Link ERP company + locations for product sync | BrandOnboarding step 2 |
| 3. Logos | Upload brand logo (PNG/JPEG/WebP) | `POST /api/v1/brands/{id}/logos` |
| 4. Brand Colors | Pick 3 colors: primary, secondary, accent | `frontend/src/components/brand/ColorPalette.tsx` |
| 5. Voice Profile | AI-generated voice style, hashtag strategy, dos/donts | BrandOnboarding step 4 |
| 6. Channels | Enable social platforms (Instagram, Facebook, etc.) | BrandOnboarding step 5 |
| 7. Products | Sync from Business Central, upload/search images | ProductsTab |
| 8. Competitors | Add competitor brands for research | CompetitorTracker |

**Result:** Brand status = `onboarding` → `active` after completing setup.

---

## Phase 2: Content Factory Activation

**Trigger:** User clicks "Start Content Factory" on brand Overview tab

**Backend:** `POST /api/v1/brands/{id}/activate` → publishes NATS message `research.trigger`

**Worker chain:** `agents/worker.py` orchestrates the sequential pipeline:

```
research.trigger → strategy.trigger → planning.trigger → content.generate
```

Each stage creates an `agent_run` record with status: `pending` → `running` → `completed`/`failed`

---

## Phase 3: Research (agent_type = "research")

**Workflow:** `agents/workflows/research/graph.py`

| Node | What it does |
|------|-------------|
| `crawl_websites` | Fetches brand website via browser-worker or direct HTTP |
| `analyze_brand` | LLM analyzes brand positioning, values, voice from website content |
| `analyze_competitors` | LLM profiles each competitor brand |
| `build_personas` | LLM creates 3-5 target audience personas with demographics, pain points, content preferences |
| `store_research` | Saves research output to DB + Qdrant vector store |

**Output:** Brand intelligence package (personas, competitor analysis, brand positioning)

---

## Phase 4: Strategy (agent_type = "strategy")

**Workflow:** `agents/workflows/strategy/graph.py`

| Node | What it does |
|------|-------------|
| `generate_positioning` | LLM creates brand positioning: value proposition, key messages, brand voice, archetype |
| `generate_content_pillars` | LLM creates 4-6 content pillars (themes) with descriptions and rationale |
| `generate_channel_strategy` | LLM creates per-channel posting strategy (frequency, best times, content types) |
| `store_strategy` | Saves strategy to DB |

**Output:** Brand positioning, content pillars, channel strategy

---

## Phase 5: Planning (agent_type = "planning")

**Workflow:** `agents/workflows/planning/graph.py`

| Node | What it does |
|------|-------------|
| `generate_campaigns` | LLM creates campaign themes for the planning period |
| `generate_strategy_document` | LLM writes a year-long content calendar strategy document |
| `generate_calendar` | LLM creates specific calendar items (posts) within the `scope_weeks` window |
| `store_calendar` | Saves calendar items to DB + strategy document as `content_calendar` agent_run |

**Key setting:** `scope_weeks` (default: 1) controls how far ahead to plan.
Only items within this window get content generated.

**Output:** Calendar items with title, channel, scheduled date, pillar, theme, target audience, content brief

---

## Phase 6: Content Generation (agent_type = "content")

**Workflow:** `agents/workflows/content/graph.py` — 10 sequential nodes

**Runs once per calendar item.** Multiple items are chained sequentially via `remaining_queue`.

| # | Node | What it does | Key detail |
|---|------|-------------|------------|
| 1 | `load_context` | Load brand intelligence, calendar item, strategy, products | Sets calendar item status → `working` |
| 2 | `generate_hook` | LLM creates scroll-stopping opening line | Uses brand voice, audience pain points, avoids recent hooks |
| 3 | `generate_caption` | LLM writes full caption with CTA | Uses positioning, pillar, audience prefs, product details |
| 4 | `generate_hashtags` | LLM generates platform-appropriate hashtags | Instagram: 20-25, LinkedIn: 3-5, X: 2-3 |
| 5 | `source_product_image` | Find real product image from gallery | NEVER AI-generates product photos; uses gallery images only |
| 6 | `generate_background` | DALL-E generates lifestyle photograph | Uses brand colors, NO TEXT/logos in image, composition rules for overlay zones |
| 7 | `apply_branding` | Overlay logo + text hook on the image | SVG→PNG via ImageMagick+rsvg-convert; places logo on monotone region; text bar at bottom-left. If product image available, Gemini replaces generic product first. |
| 8 | `adapt_platforms` | LLM adapts content for all enabled channels | Different caption length, hashtag count, CTA per platform |
| 9 | `generate_mockups` | Create platform feed preview mockups | Instagram/Facebook/LinkedIn/X mobile mockups via Pillow |
| 10 | `store_content` | Save content to DB, create approval record | Sets calendar item status → `in_review`, auto-assigns reviewer |

**Step tracking:** Each node updates `calendar_items.generation_metadata` with `current_step`, `step_index`, `total_steps` for the real-time workflow tracker UI.

**Output:** Content record with caption, hashtags, CTA, branded image, mockups, platform adaptations

---

## Phase 7: Review & Approval

**UI:** `/content/{calendar_item_id}` — Content detail page

| Element | What it shows |
|---------|--------------|
| ChannelPreview | Branded image with caption preview (shows branded version, not raw) |
| Review & Approve card | Approve/Reject buttons with feedback textarea |
| Image regeneration | Custom prompt to regenerate the background image |
| Content Editor tab | Edit caption, hashtags, CTA directly |
| Approval History tab | Timeline of approval decisions |

**Flow:**
1. Reviewer sees content in `in_review` status
2. Clicks Approve → calendar item status = `approved`
3. Or clicks Reject with feedback → status = `reworking`

---

## Phase 8: Scheduling & Publishing

**Scheduler:** `backend/app/scheduler/publish_checker.py` runs every 15 minutes

| Step | What happens |
|------|-------------|
| 1 | Find `approved` items where `scheduled_at <= now` |
| 2 | Call `publish_service.publish_to_n8n()` for each |
| 3 | n8n workflow publishes to social platform (Instagram, Facebook, etc.) |
| 4 | n8n calls back `POST /api/v1/webhooks/publish-result` with result |
| 5 | Calendar item status → `published` with `platform_post_id` |

---

## Status Flow

```
Calendar Item:  queued → working → in_review → approved → scheduled → publishing → published
                                  ↘ reworking ↗                                    ↘ failed
```

---

## Key Configuration

| Setting | Default | Where | Effect |
|---------|---------|-------|--------|
| `content_generation_days_ahead` | 7 | `app_settings` table | How far ahead morning jobs generate content |
| `scope_weeks` | 1 | Worker payload | How many weeks of calendar items to plan/generate on activation |
| `max_daily_posts` | 3 | `app_settings` table | Maximum posts per day per brand |
| `publish_check_interval_minutes` | 15 | `app_settings` table | How often the scheduler checks for due posts |

---

## File Map

| Area | Key Files |
|------|-----------|
| Worker orchestration | `agents/worker.py` |
| Content pipeline | `agents/workflows/content/graph.py`, `agents/workflows/content/nodes.py` |
| Image processing | `agents/shared/image_processing.py` (logo overlay, mockups) |
| Brand intelligence | `agents/shared/tools/database.py` → `build_brand_intelligence()` |
| Frontend pipeline tracker | `frontend/src/components/content/WorkingStageTracker.tsx` |
| Frontend content detail | `frontend/src/app/content/[id]/page.tsx` |
| Frontend brand overview | `frontend/src/components/brand/tabs/OverviewTab.tsx` |
| Scheduling | `backend/app/scheduler/publish_checker.py` |
| Publishing | `backend/app/services/publish_service.py` → n8n |
