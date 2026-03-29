# MARKAI Master Implementation Plan v2

**Date:** 2026-03-29
**Status:** Audit complete, awaiting approval to implement

---

## Critical Issues Found (15)

### A. Content Generated for DISABLED Channels

**Root cause:** The planning workflow never loads brand channel config. The LLM prompt hardcodes `instagram/facebook/linkedin` and the `adapt_platforms` node adapts to all 8 channels unconditionally. `store_calendar_items` doesn't validate enabled status.

**Impact:** User has only Instagram enabled but content was generated for LinkedIn, YouTube, Facebook.

**Fix:**
1. Planning `load_strategy` node must also load brand config (enabled channels)
2. Pass only enabled channels to the LLM planning prompt
3. `adapt_platforms` must only adapt for enabled channels
4. `store_calendar_items` must reject items for disabled channels

**Files:** `agents/workflows/planning/nodes.py`, `agents/workflows/content/nodes.py`, `agents/shared/tools/database.py`

---

### B. Content Pipeline — Items Stuck in "Queued" Forever

**Root cause:** Calendar items are created as `status='queued'` but NO code transitions them to `'working'`. The content workflow creates Content with `status='in_review'` but never updates CalendarItem. The publish_checker only watches `status='scheduled'`.

**Fix:**
1. Content workflow `load_context` → set calendar item to `'working'`
2. Content workflow `store_content` → set calendar item to `'in_review'`
3. Only process 1 item at a time (sequential)

**Files:** `agents/workflows/content/nodes.py`, `agents/shared/tools/database.py`

---

### C. Content Calendar Is Not a Strategic Document

**User requirement:** The content calendar should be TWO things:
1. **A year-long strategic document** — explains themes, sequencing rationale, content strategy for the full year. This is the reference document that the daily content generation agent reads for context.
2. **A visual calendar** — shows content pieces on dates with brand color-coding.

The queue only grabs items within the `content_generation_days_ahead` window from settings. But the strategic calendar document covers the full year.

**Current state:** Calendar is just a list of items with dates. No strategic document exists.

**Fix:**
1. Planning workflow generates a **Content Calendar Strategy Document** (markdown) stored as an agent_run output — covers full year themes, pillars, seasonal hooks
2. Planning workflow generates **calendar items** only for the `content_generation_days_ahead` window
3. A daily scheduled job checks the strategy document and populates the next day's queue
4. Intelligence page shows the strategy document alongside the visual calendar

**Files:** `agents/workflows/planning/nodes.py`, `agents/workflows/planning/state.py`, `backend/app/scheduler/morning_jobs.py`, `frontend/src/app/intelligence/page.tsx`

---

### D. No "Days Ahead" Setting

**Fix:**
1. Add `content_generation_days_ahead` to `db/init.sql` and Settings UI (default: 7)
2. Worker reads this setting before fanning out content
3. Planning generates calendar items within this window
4. Morning job tops up the queue daily from the strategy document

**Files:** `db/init.sql`, `frontend/src/app/settings/page.tsx`, `agents/worker.py`

---

### E. No Sequential Content Processing (1 at a Time)

**Root cause:** Worker fans out ALL calendar items to NATS simultaneously.

**Fix:** Worker sorts items by `scheduled_at` (nearest first), publishes one at a time. When one completes, publish the next.

**Files:** `agents/worker.py`

---

### F. Competitors Show "Incomplete" in Onboarding

**Root cause:** `BrandResponse` doesn't include `competitors` relationship. Onboarding checks `brand.competitors` which is always undefined.

**Fix:** Onboarding fetches competitors via `/brands/{id}/competitors` API call instead of relying on the brand object.

**Files:** `frontend/src/components/brand/BrandOnboarding.tsx`

---

### G. Strategy Report Shows "nan% relevant"

**Root cause:** `/api/v1/intelligence/trends` returns Competitor objects instead of TrendData. `relevance_score` is undefined → NaN.

**Fix:** Trends endpoint should extract topic/trend data from the strategy `output_payload.themes` instead of returning competitors.

**Files:** `backend/app/api/v1/intelligence.py`

---

### H. Intelligence Page Missing Formatted Reports

**Current:** Generic list. **Required:** 4 formatted report cards:
1. Research Report — market gaps, personas, competitors found
2. Marketing Strategy — positioning, pillars, audiences, cadence
3. Marketing Plan — campaigns, themes, seasonal hooks
4. Content Calendar — strategy document + visual calendar

**Files:** `frontend/src/app/intelligence/page.tsx`, `frontend/src/app/intelligence/report/[id]/page.tsx`

---

### I. Research Ignores Existing Competitors

**Root cause:** Research discovers competitors via web crawl only. Doesn't check the `competitors` table for manually added ones.

**Fix:** `analyze_competitors` loads existing DB competitors as a baseline.

**Files:** `agents/workflows/research/nodes.py`

---

### J. Calendar View Missing Brand Context

**User requirement:**
- Calendar items should show brand name (not just content title)
- Different color per brand
- Channel radio/badge on each item

**Files:** `frontend/src/components/content/CalendarView.tsx`, `frontend/src/components/content/ContentCard.tsx`

---

### K. Content Calendar Date Gaps

**Root cause:** LLM generates dates freely. No enforcement of even spacing or daily posts.

**Fix:** Planning prompt must specify: "Generate 1 post per enabled channel per day, every day within the date range. No gaps."

**Files:** `agents/workflows/planning/nodes.py`

---

### L. Settings Don't Control Scheduler

**Root cause:** Scheduler reads env vars at boot, ignores DB settings.

**Fix:** Scheduler reads from DB at job execution time.

**Files:** `backend/app/scheduler/__init__.py`

---

### M. max_daily_posts Unused

**Fix:** Enforce in planning prompt: "Maximum {max_daily_posts} posts per day across all channels."

**Files:** `agents/workflows/planning/nodes.py`

---

### N. Product Image Web Search Returns Nothing

**Fix:** Route through browser-worker (Playwright) instead of raw HTTP scraping.

**Files:** `backend/app/services/gemini_service.py`

---

### O. Auto-Discover Triggered Full Pipeline (FIXED)

**Status:** Already fixed in commit `5975e45`.

---

## Architecture: Content Calendar as Strategic Document

```
Year-long Planning (runs once on activation):
  ├── Content Calendar Strategy Document (Markdown, stored in agent_runs)
  │   └── Full year: themes by month, seasonal hooks, content pillars, rationale
  │
  └── Calendar Items (only for next N days from settings)
      └── Specific posts: title, channel, scheduled_at, theme context

Daily Top-Up Job (runs every morning):
  ├── Read the Strategy Document for tomorrow's theme/context
  ├── Generate calendar items for tomorrow (if not already queued)
  └── Trigger content generation for the nearest queued item

Content Generation (sequential, 1 at a time):
  ├── Pick nearest "queued" item → set to "working"
  ├── Read Strategy Document for context
  ├── Generate content (hook, caption, image, mockups)
  ├── Store content → set item to "in_review"
  └── Pick next → repeat
```

---

## Implementation Priority

### Phase 1: Pipeline Fundamentals (must-have)

| # | Fix | Files |
|---|-----|-------|
| 1 | **Channel filtering** — only generate for enabled channels | planning/nodes.py, content/nodes.py, database.py |
| 2 | **Status transitions** — queued→working→in_review | content/nodes.py, database.py |
| 3 | **Sequential processing** — 1 item at a time, nearest first | worker.py |
| 4 | **Onboarding competitors** — fetch via API | BrandOnboarding.tsx |
| 5 | **Days ahead setting** — add to DB + Settings UI | init.sql, settings/page.tsx |

### Phase 2: Calendar Strategy Document

| # | Fix | Files |
|---|-----|-------|
| 6 | **Year-long strategy document** — generated during planning | planning/nodes.py |
| 7 | **Daily top-up job** — reads strategy, creates tomorrow's items | morning_jobs.py |
| 8 | **Even date distribution** — enforce in planning prompts | planning/nodes.py |
| 9 | **Calendar view** — brand colors, names, channel badges | CalendarView.tsx |

### Phase 3: Reports & Intelligence

| # | Fix | Files |
|---|-----|-------|
| 10 | **Fix nan% trends** — return real trend data | intelligence.py |
| 11 | **Research loads DB competitors** | research/nodes.py |
| 12 | **Intelligence page** — 4 formatted report cards | intelligence/page.tsx |
| 13 | **max_daily_posts enforcement** | planning/nodes.py |

### Phase 4: Infrastructure

| # | Fix | Files |
|---|-----|-------|
| 14 | **Scheduler reads DB settings** | scheduler/__init__.py |
| 15 | **Image search via browser-worker** | gemini_service.py |

---

## Files to Modify (18 files)

### Agents (5 files)
1. `agents/workflows/planning/nodes.py` — channel filtering, even dates, strategy document, max_daily_posts
2. `agents/workflows/planning/state.py` — add enabled_channels field
3. `agents/workflows/content/nodes.py` — status transitions, channel validation
4. `agents/workflows/research/nodes.py` — load DB competitors
5. `agents/worker.py` — sequential fan-out, days_ahead

### Backend (5 files)
6. `backend/app/api/v1/intelligence.py` — fix trends endpoint
7. `backend/app/scheduler/morning_jobs.py` — daily content top-up job
8. `backend/app/scheduler/__init__.py` — read DB settings
9. `backend/app/services/gemini_service.py` — browser-worker for images
10. `db/init.sql` — content_generation_days_ahead setting

### Frontend (5 files)
11. `frontend/src/components/brand/BrandOnboarding.tsx` — competitors API check
12. `frontend/src/app/intelligence/page.tsx` — 4 report cards
13. `frontend/src/app/settings/page.tsx` — days_ahead slider
14. `frontend/src/components/content/CalendarView.tsx` — brand colors, badges
15. `frontend/src/components/content/ContentCard.tsx` — brand context

### Shared (3 files)
16. `agents/shared/tools/database.py` — channel validation in store_calendar_items, status update helpers
17. `frontend/src/types/index.ts` — updated types
18. `backend/app/models/calendar_item.py` — verify status values

---

## Expected End-to-End Flow After All Fixes

```
1. Create Brand → status: onboarding
2. Complete Onboarding (name, voice, channels, logos required)
3. Click "Start Content Factory"
4. Research runs → discovers competitors + loads existing ones from DB
5. Strategy runs → generates positioning, pillars, cadence, themes
6. Planning runs:
   a. Generates year-long Content Calendar Strategy Document
   b. Generates calendar items for next N days (from settings)
   c. Items ONLY for enabled channels
   d. Even daily distribution, max_daily_posts respected
   e. Items created as "queued", sorted by scheduled_at
7. Brand status → "active"
8. Content generation (sequential, 1 at a time):
   a. Pick nearest queued item → set to "working"
   b. Read Strategy Document for theme context
   c. Generate content (hook, caption, image, mockups)
   d. Store → set to "in_review"
   e. Pick next → repeat
9. Daily morning job:
   a. Read Strategy Document for tomorrow's theme
   b. Create calendar items for tomorrow if not already queued
   c. Trigger content generation for nearest queued items
10. User reviews in Content Studio → approves → "approved"
11. User schedules → "scheduled"
12. Publish checker → dispatches to n8n → "published"
```
