# MARKAI Master Implementation Plan — Report Rendering, Pipeline & UX Fixes

**Date:** 2026-03-30
**Status:** Implemented
**Scope:** 7 issues across backend pipeline, agent workflows, and frontend rendering
**Estimated files to modify:** 8
**Risk level:** Medium (touches pipeline logic and main report page)

---

## Executive Summary

After a comprehensive audit of the codebase, deployed logs, sample reports, and web research, this plan addresses every known issue in the current MARKAI deployment. The issues fall into three categories:

1. **Pipeline logic bugs** — scope_weeks too short, missing agent_run type for content calendar, naming inconsistencies
2. **Report rendering crashes** — React error #31 from objects rendered as children, raw JSON dumps instead of formatted output
3. **UX gaps** — overview page doesn't reflect pipeline progress, labels don't match expectations

---

## Issue Inventory

| # | Severity | Category | Summary |
|---|----------|----------|---------|
| 1 | P0 | Pipeline | `scope_weeks=2` produces only 2 weeks of campaigns instead of a quarter |
| 2 | P0 | Pipeline | `store_strategy()` hardcodes `agent_type='strategy'` — content calendar agent_run never created |
| 3 | P0 | Rendering | Research report crashes: `language_mix` object rendered as React child (Error #31) |
| 4 | P0 | Rendering | Strategy report dumps raw JSON for positioning, cadence, and other object fields |
| 5 | P1 | UX | "Content Plan" should be "Marketing Plan" across UI |
| 6 | P1 | Rendering | Multiple `JSON.stringify()` fallbacks across report page (lines 1271, 1461, 1592, 1615, 1681) |
| 7 | P1 | Pipeline | `content_calendar_strategy` report detection uses wrong `agent_type` check |

---

## Phase 1: Pipeline Fixes (Backend + Agents)

### 1.1 Fix `scope_weeks` — Activation Should Plan a Full Quarter

**File:** `backend/app/api/v1/brands.py`
**Line:** 193
**Current:** `"scope_weeks": 2`
**Change to:** `"scope_weeks": 12`

**Rationale:** 2 weeks produces only 2 tiny campaigns. 12 weeks (one quarter) gives the LLM enough runway to create meaningful campaigns with proper pillar rotation, seasonal themes, and cultural events (important for the Mauritius market). The daily `content_generation_days_ahead` setting (default 7) separately controls which items get content generated each day.

**Impact:** Planning workflow will generate ~84 days of calendar items (12 weeks x 7 days x enabled channels). The strategy document already generates a full 12-month roadmap regardless of scope_weeks.

---

### 1.2 Fix `store_strategy()` — Support Custom `agent_type`

**File:** `agents/shared/tools/database.py`
**Function:** `store_strategy()` (lines 144-161)

**Current SQL (line 151):**
```sql
INSERT INTO agent_runs (id, brand_id, agent_type, trigger, status, output_payload, started_at, completed_at)
VALUES (:id, :brand_id, 'strategy', 'manual', 'completed', :output_payload, :now, :now)
```

**Change:** Add `agent_type` parameter to function signature and use it in SQL:
```python
async def store_strategy(brand_id: str, strategy_data: dict[str, Any], agent_type: str = "strategy") -> str:
```

Update SQL to use `:agent_type` parameter instead of hardcoded `'strategy'`.

**Callers to update:**

1. `agents/workflows/strategy/nodes.py` lines 154, 169 — keep default `agent_type="strategy"` (no change needed)
2. `agents/workflows/planning/nodes.py` lines 305-311 — pass `agent_type="content_calendar"`:
   ```python
   await store_strategy(brand_id, {...}, agent_type="content_calendar")
   ```

**Why `"content_calendar"` not `"content_calendar_strategy"`:** The frontend IntelligenceTab (line 69) and OverviewTab (line 254) both look for `agent_type="content_calendar"`. The report detail page currently checks `agentType === "content_calendar_strategy"` (line 365) — this also needs updating to match.

---

### 1.3 Fix `agent_runs` CHECK Constraint — Already Done

The `trigger` CHECK constraint was already fixed to include `'activation'` in the previous commit. No further action needed.

---

## Phase 2: Frontend Report Rendering Fixes

### 2.1 Create `SafeRender` Utility Component

**New file:** `frontend/src/components/ui/safe-render.tsx`

This utility provides crash-proof rendering for any unknown data structure from LLM output. Core functions:

- **`renderValue(value: unknown): ReactNode`** — converts any value to a safe React node
  - `null/undefined` -> `null`
  - `string` -> `<span>` (or `<ReactMarkdown>` if multiline/long)
  - `number` -> formatted string
  - `boolean` -> "Yes"/"No" badge
  - `string[]` -> flex-wrap badges
  - `object[]` (uniform) -> auto-generated table
  - `Record<string, string>` (small flat object like language_mix) -> inline key-value badges: "Kreol 40%, French 35%, English 25%"
  - `Record<string, unknown>` (nested) -> definition list with recursive rendering
  - Ultimate fallback -> `String(value)` (never crashes)

- **`<SafeValue value={...} />`** — component wrapper for JSX use
- **`<KeyValueBadges data={...} />`** — renders `{Kreol: "40%", French: "35%"}` as inline badges
- **`formatKeyValue(obj): string`** — converts to "Kreol 40%, French 35%, English 25%" string

### 2.2 Fix Research Report — `language_mix` Crash (React Error #31)

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 988

**Current:**
```tsx
<span>{persona.content_preferences.language_mix}</span>
```

**Fix:**
```tsx
<span>
  {typeof persona.content_preferences.language_mix === "string"
    ? persona.content_preferences.language_mix
    : typeof persona.content_preferences.language_mix === "object"
    ? formatKeyValue(persona.content_preferences.language_mix)
    : null}
</span>
```

Also update the type definition in `frontend/src/types/index.ts` line 185:
```typescript
// Before:
language_mix?: string;
// After:
language_mix?: string | Record<string, string>;
```

### 2.3 Fix Strategy Report — Positioning Section

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Lines:** 1259-1319

**Current (line 1271):**
```tsx
{typeof positioning === "string" ? positioning : JSON.stringify(positioning, null, 2)}
```

**Fix:** When `positioning` is an object, render its fields as structured cards:

- **`brand_voice`** -> blockquote card with italic text
- **`key_messages`** -> numbered list with bullet points
- **`brand_archetype`** -> badge in a highlighted box (already partially handled at line 1277, but only from `output.brand_archetype` — should also check `positioning.brand_archetype`)
- **`emotional_territory`** -> badge in highlighted box (same issue — line 1283)
- **`competitive_differentiation`** -> table (already handled at line 1292 from `output.competitive_differentiation`, should also check `positioning.competitive_differentiation`)
- **`value_proposition`** -> highlighted text box
- Any other keys -> render via `<SafeValue>`

The key insight is that `positioning` may contain ALL the strategy data as nested fields, while the current code looks for them as separate top-level `output.*` fields. The fix should check both locations.

### 2.4 Fix Strategy Report — Posting Cadence

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 1461

**Current:**
```tsx
{typeof schedule === "string" ? schedule : JSON.stringify(schedule)}
```

**Fix:**
```tsx
<SafeValue value={schedule} />
```

### 2.5 Fix Planning Report — Calendar Summary

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 1592

**Current:**
```tsx
{JSON.stringify(calendarSummary, null, 2)}
```

**Fix:**
```tsx
{typeof calendarSummary === "string"
  ? <ReactMarkdown>{calendarSummary}</ReactMarkdown>
  : <SafeValue value={calendarSummary} />}
```

### 2.6 Fix Content Calendar Strategy — Strategy Document

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 1615

**Current:**
```tsx
{typeof strategyDocument === "string" ? strategyDocument : JSON.stringify(strategyDocument, null, 2)}
```

**Fix:**
```tsx
{typeof strategyDocument === "string"
  ? <ReactMarkdown>{strategyDocument}</ReactMarkdown>
  : <SafeValue value={strategyDocument} />}
```

### 2.7 Fix Catch-All Fallback

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 1681

**Current:**
```tsx
{JSON.stringify(output, null, 2)}
```

**Fix:**
```tsx
<SafeValue value={output} />
```

### 2.8 Fix Content Calendar Report Type Detection

**File:** `frontend/src/app/intelligence/report/[id]/page.tsx`
**Line:** 365

**Current:**
```tsx
const isContentCalendar = agentType === "content_calendar_strategy";
```

**Fix:**
```tsx
const isContentCalendar = agentType === "content_calendar" || agentType === "content_calendar_strategy";
```

This ensures the report page can render content calendar reports stored under either agent_type (backwards compatible with any existing data).

---

## Phase 3: UI Label & Naming Fixes

### 3.1 Rename "Content Plan" to "Marketing Plan"

**File:** `frontend/src/components/brand/tabs/IntelligenceTab.tsx`
**Line:** 68

**Current:**
```typescript
{ agent_type: "planning", title: "Content Plan", ... }
```

**Fix:**
```typescript
{ agent_type: "planning", title: "Marketing Plan", ... }
```

### 3.2 Verify OverviewTab Labels

**File:** `frontend/src/components/brand/tabs/OverviewTab.tsx`
**Line:** 253

**Current:**
```typescript
{ key: "planning", label: "Marketing Plan", ... }
```

This is already correct. No change needed.

---

## Phase 4: Type Definition Fixes

### 4.1 Update `language_mix` Type

**File:** `frontend/src/types/index.ts`
**Line:** 185

```typescript
// Before:
language_mix?: string;
// After:
language_mix?: string | Record<string, string>;
```

### 4.2 Update `positioning` Type

**File:** `frontend/src/types/index.ts`
**Line:** 82

```typescript
// Before:
positioning?: string;
// After:
positioning?: string | Record<string, unknown>;
```

---

## Implementation Order

Execute in this exact order to minimize risk:

| Step | Phase | What | Files | Risk |
|------|-------|------|-------|------|
| 1 | 2.1 | Create `safe-render.tsx` utility | NEW: `components/ui/safe-render.tsx` | None (new file) |
| 2 | 4.1-4.2 | Fix type definitions | `types/index.ts` | None (type-only) |
| 3 | 2.2 | Fix language_mix crash | `report/[id]/page.tsx` | Low (targeted fix) |
| 4 | 2.3-2.7 | Fix all JSON.stringify fallbacks | `report/[id]/page.tsx` | Medium (multiple edits) |
| 5 | 2.8 | Fix content calendar type detection | `report/[id]/page.tsx` | Low |
| 6 | 3.1 | Rename to Marketing Plan | `IntelligenceTab.tsx` | None (label only) |
| 7 | 1.1 | Fix scope_weeks | `brands.py` | Low (config change) |
| 8 | 1.2 | Fix store_strategy agent_type | `database.py`, `planning/nodes.py` | Medium (pipeline logic) |
| 9 | - | Rebuild and deploy | Docker | Standard |

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `frontend/src/components/ui/safe-render.tsx` | NEW — SafeValue, renderValue, KeyValueBadges utilities |
| `frontend/src/types/index.ts` | Fix language_mix and positioning types |
| `frontend/src/app/intelligence/report/[id]/page.tsx` | Fix language_mix crash, 5 JSON.stringify replacements, content_calendar detection |
| `frontend/src/components/brand/tabs/IntelligenceTab.tsx` | Rename "Content Plan" to "Marketing Plan" |
| `backend/app/api/v1/brands.py` | scope_weeks: 2 -> 12 |
| `agents/shared/tools/database.py` | store_strategy() accepts agent_type parameter |
| `agents/workflows/planning/nodes.py` | Pass agent_type="content_calendar" to store_strategy |

**Total: 7 files modified, 1 new file created**

---

## Post-Completion Verification Audit

After all fixes are implemented, verify each item:

### Pipeline Verification

- [ ] **scope_weeks:** Read `brands.py` line 193 — confirm value is `12`
- [ ] **store_strategy signature:** Read `database.py` — confirm `agent_type` parameter exists with default `"strategy"`
- [ ] **store_strategy SQL:** Confirm INSERT uses `:agent_type` parameter, not hardcoded string
- [ ] **planning caller:** Read `planning/nodes.py` — confirm `store_strategy(..., agent_type="content_calendar")` call
- [ ] **strategy caller:** Read `strategy/nodes.py` — confirm existing calls still work (no agent_type arg = default "strategy")
- [ ] **agent_runs constraint:** Confirm CHECK constraint includes `'activation'`

### Report Rendering Verification

- [ ] **safe-render.tsx exists:** Confirm file created with `renderValue`, `SafeValue`, `KeyValueBadges`, `formatKeyValue` exports
- [ ] **language_mix (line ~988):** Confirm uses typeof guard or SafeValue — NOT direct object render
- [ ] **positioning (line ~1271):** Confirm NO `JSON.stringify` — uses structured rendering or SafeValue
- [ ] **cadence (line ~1461):** Confirm NO `JSON.stringify` — uses SafeValue
- [ ] **calendar summary (line ~1592):** Confirm NO `JSON.stringify` — uses ReactMarkdown or SafeValue
- [ ] **strategy document (line ~1615):** Confirm NO `JSON.stringify` — uses ReactMarkdown or SafeValue
- [ ] **catch-all (line ~1681):** Confirm NO `JSON.stringify` — uses SafeValue
- [ ] **content_calendar detection (line ~365):** Confirm checks BOTH `"content_calendar"` and `"content_calendar_strategy"`

### Type Verification

- [ ] **language_mix type:** Confirm `string | Record<string, string>` in types/index.ts
- [ ] **positioning type:** Confirm `string | Record<string, unknown>` in types/index.ts

### UI Label Verification

- [ ] **IntelligenceTab:** Confirm "Marketing Plan" label (not "Content Plan")
- [ ] **OverviewTab:** Confirm "Marketing Plan" label (already correct)

### Grep Verification (Zero Violations)

- [ ] `grep -n "JSON.stringify" report/[id]/page.tsx` — should return ZERO matches (all replaced with SafeValue)
- [ ] `grep -rn "content_calendar_strategy" frontend/` — confirm report page accepts both agent_types
- [ ] `grep -n "scope_weeks.*2" backend/` — should return ZERO matches (changed to 12)
- [ ] `grep -n "'strategy'" agents/shared/tools/database.py` — should NOT appear in store_strategy INSERT (now parameterized)

### End-to-End Smoke Test

After deploying to VPS:

1. **Delete existing brand** and create fresh
2. **Complete onboarding** — verify 7/7 on both sidebar and overview
3. **Click "Start Content Factory"** from overview page (not onboarding dialog)
4. **Watch pipeline progress** — should show Research -> Strategy -> Marketing Plan -> Content Calendar stages with real-time status
5. **Verify brand transitions to "active"** after planning completes
6. **Open Research Report** — should NOT crash, language_mix should render as "Kreol 40%, French 35%, English 25%"
7. **Open Strategy Report** — positioning should render as structured cards, NOT raw JSON
8. **Open Marketing Plan Report** — should show campaigns for ~12 weeks
9. **Open Content Calendar Report** — should exist (not stuck on "pending") and show formatted strategy document
10. **Verify "Marketing Plan" label** on both IntelligenceTab and OverviewTab

---

## Deployment Steps

```bash
cd /var/www/markai
git pull origin main

# Wipe DB for clean schema (scope_weeks change requires fresh planning)
docker compose -f docker-compose.yml -f docker-compose.vps.yml down
docker volume rm markai_pgdata markai_qdrant_data || true

# Rebuild all services (backend + agents + frontend all changed)
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents

# Start
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

# Wait and verify
sleep 20
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
```

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| scope_weeks 2 to 12 | Planning takes longer, generates more items | LLM max_tokens=16384 already handles large output |
| store_strategy agent_type parameter | Could break existing strategy storage | Default parameter "strategy" preserves existing behavior |
| SafeValue replacing JSON.stringify | Could change visual layout | SafeValue is strictly better — formatted instead of raw |
| Content calendar agent_type change | Old data in DB still has agent_type="strategy" | Report page checks both values for backwards compat |

---

**This plan is ready for review. No implementation has started.**
