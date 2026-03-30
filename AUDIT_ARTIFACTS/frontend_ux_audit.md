# Phase 8 -- Frontend & UI/UX Audit

**Date**: 2026-03-30
**Auditor**: Claude Opus 4.6 (automated)
**Scope**: All files under `frontend/src/components/` and `frontend/src/app/`

---

## 8.1 Component Architecture

### 8.1.1 Component Hierarchy & Composition

```
layout.tsx (RootLayout)
  providers-wrapper.tsx (Providers)
    SessionProvider (next-auth)
      ThemeProvider (next-themes)
        AuthGate
          Sidebar
            BrandSwitcher
          Header
            NotificationDropdown
            UserMenu
          <main>{children}</main>  ← Page routes
          Toaster (sonner)
```

**Page Routes (20 pages)**:
- `/` -- DashboardPage
- `/brands` -- BrandsPage
- `/brands/new` -- NewBrandPage
- `/brands/[id]` -- BrandDetailPage (920 lines -- see oversized note below)
- `/content` -- ContentStudioPage
- `/content/[id]` -- ContentDetailPage
- `/content/calendar` -- ContentCalendarPage
- `/approvals` -- ApprovalsPage
- `/analytics` -- AnalyticsPage
- `/intelligence` -- IntelligencePage
- `/intelligence/report/[id]` -- ReportDetailPage
- `/intelligence/products` -- ProductImagesPage
- `/learning` -- LearningPage
- `/providers` -- ProvidersPage
- `/prompts` -- PromptsPage
- `/system` -- SystemPage
- `/system/audit` -- AuditLogPage
- `/settings` -- SettingsPage
- `/settings/users` -- UsersPage
- `/auth/signin` -- SignInPage

**Component Groups (48 component files)**:
- `ui/` (17) -- shadcn/ui primitives + custom confirm-dialog, safe-render
- `brand/` (5 + 8 tabs) -- BrandCard, BrandForm, BrandOnboarding, CompetitorTracker, WorkflowStatus
- `content/` (6) -- KanbanBoard, ContentCard, ContentEditor, CalendarView, AssetPreview, PlatformMockups
- `approval/` (2) -- ApprovalActions, ApprovalHistory
- `analytics/` (3) -- EngagementChart, PerformanceGrid, PostingHeatmap
- `system/` (3) -- ServiceHealth, WorkflowMonitor, QueueDepth
- `layout/` (3) -- Sidebar, Header, BrandSwitcher

### 8.1.2 Prop Drilling -- SIGNIFICANT ISSUE

**Severity: MEDIUM**

The `BrandDetailPage` (`brands/[id]/page.tsx`, 920 lines) is the worst offender. It holds ~30 pieces of state and passes them as props to 8 tab components. The `OverviewTab` alone receives **17 props**. The `ProductsTab` receives **26 props**.

Despite having `zustand` in `package.json`, it is **never imported or used anywhere** in the codebase. All state management relies on React's `useState`/`useCallback`/`useEffect` with prop drilling.

**Affected Components (prop drilling chains)**:
| Parent | Child | Props Drilled |
|--------|-------|--------------|
| BrandDetailPage | OverviewTab | 17 props |
| BrandDetailPage | ProductsTab | 26 props |
| BrandDetailPage | ChannelsTab | 12 props |
| BrandDetailPage | LogosTab | 6 props |
| BrandDetailPage | IntelligenceTab | 5 props |

**Recommendation**: Create a `BrandDetailContext` (or use the already-installed Zustand store) to eliminate prop drilling in the brand detail page. This would reduce the OverviewTab and ProductsTab interfaces from 17-26 props to 0-2.

### 8.1.3 Oversized Components -- MUST REFACTOR

**Severity: HIGH**

| File | Lines | Problem |
|------|-------|---------|
| `app/brands/[id]/page.tsx` | 920 | God component: holds 30+ state vars, 15+ handlers, all tab rendering logic. Should be split into a context provider + lightweight shell. |
| `components/brand/BrandForm.tsx` | 660 | Large but more acceptable -- form with AI generation. Could extract AI actions into a custom hook. |
| `components/brand/BrandOnboarding.tsx` | 523 | Moderate. Step rendering is all inline. Could extract each step into its own component. |
| `components/content/CalendarView.tsx` | 320 | Has an inline modal overlay instead of using the Dialog component from ui/. |
| `app/settings/page.tsx` | 441 | Large but linear form; acceptable complexity. |
| `app/system/page.tsx` | 403 | Borderline; could extract the Agent Runs table and Trigger Workflows table. |
| `app/intelligence/page.tsx` | 463 | Contains 4 inline preview renderer sub-components; reasonable. |
| `app/content/page.tsx` | 346 | Contains inline dialog form; could extract. |

### 8.1.4 Loading, Error, and Empty States

**Good coverage overall**. Nearly every page/component handles all three states:

| Page/Component | Loading | Error | Empty |
|----------------|---------|-------|-------|
| DashboardPage | Skeleton cards | Error message | Handled per section |
| BrandsPage | Skeleton grid | Error + Retry button | "No brands yet" + CTA |
| BrandDetailPage | Skeleton | Toast error | Per-section empty states |
| ContentStudioPage | Skeleton | Toast error | "No content yet" |
| ContentCalendarPage | Skeleton | Silent fail | "No scheduled content" |
| ApprovalsPage | Skeleton list | Toast error | "No pending approvals" |
| AnalyticsPage | Skeleton grid | Toast error | Per-chart "No data" |
| IntelligencePage | Skeleton grid | Toast error | Per-card empty state |
| SettingsPage | Skeleton | Toast + defaults | N/A (always has defaults) |
| SystemPage | Skeleton grid | Toast error | Per-section empty states |
| ContentDetailPage | Skeleton | "Content not found" + back button | N/A |
| AuthGate | Skeleton centered | Sign-in card | N/A |
| BrandSwitcher | Pulse animation | Silent | N/A |

**Gaps found**:
1. **ContentCalendarPage**: Error state is swallowed silently (`catch { setItems([]) }`). No error message shown to user.
2. **Header notifications**: Errors silently ignored. If the notifications API is permanently broken, user never knows.
3. **BrandDetailPage products/competitors**: Fetched with `.catch(() => {})` -- errors completely invisible.

### 8.1.5 Form Handling

| Form | Validation | Submission Feedback | Error Display |
|------|-----------|-------------------|--------------|
| BrandForm | Name required, URL validation | "Saving..." button state | Toast errors |
| ContentEditor | None (relies on backend) | "Saving..." button state | Toast errors |
| New Content Dialog | Brand/Title/Channel required | "Creating..." button state | Toast errors |
| ApprovalActions | None needed | Loading state on buttons | Toast errors |
| CompetitorTracker form | Name required | "Saving..." button state | Toast errors |
| SettingsPage | None (all selects/sliders) | "Saving..." button state | Toast errors |

**Gaps found**:
1. **BrandForm**: URL validation is only performed on submit. No inline validation feedback as user types. Invalid URLs only reported on save attempt.
2. **Content Dialog**: The form uses plain `<label>` elements instead of the shadcn `<Label>` component, and the `<textarea>` is a raw HTML element instead of the project's `<Textarea>` component. Inconsistent with rest of codebase.
3. **No form-level error summaries**: All validation errors are individual toasts. If multiple fields fail, user sees multiple sequential toasts.

---

## 8.2 Accessibility (a11y)

### 8.2.1 Semantic HTML

**Severity: MEDIUM**

**Good**:
- `<html lang="en">` is set in layout.tsx
- `<header>`, `<nav>`, `<main>` elements are used correctly in the shell
- `<form>` element is used in BrandForm with `onSubmit`
- `<table>` elements used for tabular data (products, agent runs)
- `<dl>/<dt>/<dd>` used in safe-render.tsx for definition lists

**Issues**:
1. **Sidebar navigation**: Uses `<nav>` but individual items are `<Link>` without `role` or `aria-current`. Active link should have `aria-current="page"`.
2. **KanbanBoard columns**: Kanban columns lack `role="list"` and items lack `role="listitem"`. Screen readers cannot understand the board structure.
3. **CalendarView**: Calendar grid is a `<div>` grid, not a `<table>`. No `role="grid"` or `role="gridcell"`. Weekday headers are divs, not `<th>`.
4. **BrandOnboarding stepper**: Uses `<button>` elements (good) but has no `role="tablist"` / `role="tab"` pattern for the vertical stepper.
5. **Product table checkboxes**: Native `<input type="checkbox">` without associated labels. Should have `aria-label` at minimum.

### 8.2.2 ARIA Attributes

**Good**:
- Theme toggle button: `aria-label="Toggle theme"` and `<span className="sr-only">Toggle theme</span>`
- Notification bell: Dynamic `aria-label` with unread count
- User avatar button: Has avatar with `alt` text
- Badge on notification: `aria-hidden="true"` (decorative)

**Issues**:
1. **Sidebar collapse button**: No `aria-label`. Should indicate "Collapse sidebar" / "Expand sidebar".
2. **Sidebar collapse state**: No `aria-expanded` on the toggle button.
3. **BrandSwitcher Select**: Missing `aria-label` for screen readers.
4. **Kanban drag-and-drop**: No ARIA live regions to announce drag state changes. `@dnd-kit` provides some accessibility, but no custom announcements are configured.
5. **CalendarView expanded day overlay**: Uses `div` with `onClick` as a modal backdrop but no `role="dialog"`, `aria-modal`, or focus trap.
6. **Product table "select all" checkbox**: No label or `aria-label`.
7. **Multiple icon-only buttons throughout** (settings gear on channels, stock expand, gallery open) lack `aria-label`.

### 8.2.3 Keyboard Navigation

**Good**:
- All interactive elements use `<button>` or `<a>` (keyboard accessible by default)
- KanbanBoard uses `KeyboardSensor` from `@dnd-kit/core`
- Dialogs use Radix primitives which handle focus trapping

**Issues**:
1. **CalendarView expanded day overlay**: No focus trap. Pressing Tab after opening will tab into elements behind the overlay. No Escape key handler.
2. **CalendarView drag-and-drop**: Uses native HTML5 drag (`draggable`), which has poor keyboard accessibility. Should use `@dnd-kit` like the KanbanBoard does.
3. **BrandCard**: Entire card is wrapped in `<Link>`, but status dots inside are not interactive -- acceptable but the card itself should have a more descriptive `aria-label`.
4. **ProductsTab table**: Row click handlers are on `<td>` elements, not on proper interactive elements. The stock expansion button is a `<button>` (good) but others are table cells.

### 8.2.4 Form Labels

**Good**:
- BrandForm: All fields have `<Label htmlFor="...">` with matching `id` on inputs
- ContentEditor: All fields labeled
- CompetitorTracker: All fields labeled
- SettingsPage: All fields have `<Label htmlFor="...">`
- ApprovalActions: Comment textarea is labeled with unique `id`

**Issues**:
1. **Content creation dialog**: Uses `<label className="text-sm font-medium">` without `htmlFor`. These are visual labels only, not programmatically associated with their inputs.
2. **ProductsTab filter selects**: Raw `<select>` elements with `<Label>` nearby but no `htmlFor`/`id` binding.
3. **LogosTab upload select**: Raw `<select>` without `id` matching `htmlFor`.
4. **SettingsPage timezone/scheduler selects**: All use raw `<select>` with matching `id`/`htmlFor` (good).

### 8.2.5 Alt Text for Images

**Good**:
- LogosTab: `alt={label}` on logo images
- PlatformMockups: `alt={`${platform} preview`}`
- AvatarImage: `alt={session?.user?.name || "User avatar"}`
- ContentEditor: `alt={`Asset ${i + 1}`}`

**Issues**:
1. **ProductsTab product images**: `alt=""` on product thumbnail images. Should use product name.
2. **Product gallery images**: `alt=""` on all gallery images.
3. **BrandCard AvatarImage**: No explicit `alt` (uses AvatarFallback as fallback text, which is good).
4. **CalendarView**: No images, but calendar item text content relies entirely on `title` attribute tooltips.

### 8.2.6 Color Contrast Concerns

**Severity: LOW-MEDIUM**

1. **Status dots** (2.5x2.5 green/orange/cyan circles in BrandCard): These are the only indicator of brand status. Color alone is used -- no accompanying text for "active" status (though "onboarding" and "activating" do have text labels). The "active" state only shows a green dot with `title="Active"`.
2. **Channel icons in BrandCard/OverviewTab**: Disabled channels show `text-muted-foreground/30` (30% opacity) which may fail WCAG AA contrast on both light and dark backgrounds.
3. **CalendarView items**: `text-[10px]` and `text-[8px]` font sizes are extremely small. Combined with color-coded backgrounds, some combinations (e.g., `bg-slate-200 text-slate-800` at 8px) may be difficult to read.
4. **Various `text-[10px]` badges**: Used extensively throughout BrandCard, KanbanBoard, CalendarView, and ProductsTab. This 10px text may be below WCAG minimum for readability.
5. **Queue depth progress bars**: Color-only differentiation (green/blue/amber/red) for queue states. The legend below mitigates this.

---

## 8.3 Responsive Design

### 8.3.1 Viewport Meta Tag

**Good**: Next.js 16 automatically injects `<meta name="viewport" content="width=device-width, initial-scale=1">`.

### 8.3.2 Mobile Responsiveness

**Severity: HIGH**

**Layout Shell Issue**: The main layout uses `flex h-screen overflow-hidden` with a sidebar that is either `w-64` or `w-16`. There is **no mobile breakpoint** to hide the sidebar entirely. On mobile devices:

1. **Sidebar takes fixed 64px/256px** regardless of screen width. On a 375px phone screen, the sidebar consumes 17-68% of the viewport.
2. **No hamburger menu**: No way to toggle sidebar on mobile. The collapse button reduces to 64px but does not fully hide.
3. **No mobile-specific navigation**: No bottom nav bar or sheet-style mobile menu.

**Breakpoint Usage (Tailwind)**:
| Pattern | Usage | Quality |
|---------|-------|---------|
| `md:grid-cols-2` | BrandForm, BrandsPage grid, ChannelsTab | Good |
| `lg:grid-cols-3` | BrandsPage, system page | Good |
| `lg:grid-cols-4` | Dashboard stat cards | Good |
| `sm:grid-cols-2` | KanbanBoard columns | Good |
| `lg:grid-cols-5` | KanbanBoard row 2 | Good |
| `xl:grid-cols-3` | ChannelsTab, LogosTab | Good |
| `sm:flex-row` | ApprovalActions buttons | Good |
| `flex-wrap gap-4` | Various toolbars | Good |

**Specific Issues**:
1. **KanbanBoard**: On mobile, 4-column and 5-column rows collapse to `grid-cols-1`. Functional but very tall scrolling.
2. **CalendarView**: 7-column grid (`grid-cols-7`) never changes. On mobile, each cell is ~53px wide (375px/7), making content unreadable.
3. **ProductsTab table**: `overflow-x-auto` is set (good), but the filter bar has many horizontal elements that may wrap awkwardly.
4. **BrandOnboarding**: Left stepper is `hidden md:flex` (good -- mobile shows only the accordion).
5. **OverviewTab Content Factory pipeline**: 5 circles in a row with `overflow-x-auto` -- works but may require horizontal scroll on mobile.
6. **Header**: No responsiveness issues; clean flex layout.

### 8.3.3 Mobile-First Assessment

The codebase is **desktop-first** design. Responsive classes are added for medium/large screens (`md:`, `lg:`, `xl:`) to expand layouts. Mobile gets the default (usually single column). This is acceptable but the fixed sidebar makes the mobile experience fundamentally broken.

---

## 8.4 State Management

### 8.4.1 State Management Strategy

**Primary**: React `useState` + `useCallback` + `useEffect` hooks (component-local state).
**Authentication**: `next-auth` `SessionProvider` + `useSession()`.
**Theme**: `next-themes` `ThemeProvider`.
**Cross-component communication**: `window.dispatchEvent(new CustomEvent("brand-changed"))` in BrandSwitcher.
**Installed but unused**: `zustand` v5.0.3 is in `package.json` but never imported.

### 8.4.2 Prop Drilling Assessment

**Severity: HIGH** (detailed in 8.1.2)

The BrandDetailPage is the primary offender with 30+ state variables passed as props to child tabs. No React Context or Zustand store is used for shared brand state. The `BrandSwitcher` communicates via DOM CustomEvents rather than React context or a store, which is fragile and not type-safe.

### 8.4.3 Stale State Risks

**Severity: MEDIUM**

1. **BrandSwitcher global filter**: When user selects a brand in the sidebar, it dispatches `brand-changed` CustomEvent. Only `ContentStudioPage` listens for this event. The Dashboard, Analytics, Approvals, Intelligence, and System pages do NOT listen -- they always show all-brands data regardless of the switcher selection. This is inconsistent and confusing.

2. **BrandDetailPage onboarding progress**: Computed inline from `brand`, `products`, and `competitors` state. If the user updates the brand in the Edit tab, the onboarding progress does not recalculate until the brand state is refreshed. The edit handler does `setBrand(updated)`, so this mostly works, but products/competitors are fetched separately and may be stale.

3. **BrandDetailPage polling effects**: Multiple `useEffect` hooks poll for agent runs:
   - `fetchIntelligence` polls every 5s when research tab has running jobs
   - Activation polling polls every 3s while `brand.status === "activating"`
   - WorkflowStatus component polls every 5s independently

   These can overlap, causing redundant API calls and potential state update races.

4. **Header notification polling**: Polls every 30 seconds. The `fetchNotifications` callback is memoized with `useCallback([], [])` (no dependencies), which is correct. However, if the component unmounts and remounts (e.g., React Strict Mode), the interval ref is properly cleaned up.

5. **ContentStudioPage**: Maintains an `AbortController` ref that properly cancels in-flight requests on brand switch. Good pattern.

### 8.4.4 Race Conditions

**Severity: MEDIUM**

1. **BrandDetailPage initial fetch**: Fires 6+ parallel API calls on mount (brand, content, metrics, products, pipeline runs, competitors). All use independent `setState` calls. If the component unmounts before all settle, the AbortController cancels them (good). However, `.catch(() => {})` on 3 of these calls means errors are invisible.

2. **BrandDetailPage handleBulkProductActive**: Loops through products with sequential `api.put()` calls in a `for...of` loop. If 50 products are toggled, this fires 50 sequential API calls. No batching, no error accumulation. If one fails, the rest still execute, but the UI may show inconsistent state.

3. **BrandOnboarding handleActivate**: Calls `complete-onboarding` then `activate` sequentially. If the first succeeds but the second fails, the brand may be in a "completed but not activated" state. No rollback mechanism.

4. **Multiple polling intervals**: The BrandDetailPage can have 3 concurrent polling intervals active simultaneously (intelligence polling, activation polling, WorkflowStatus component polling). These all update overlapping state (`research`, `pipelineRuns`).

---

## Summary of Findings

### Critical Issues (Must Fix)
| # | Category | Issue |
|---|----------|-------|
| C1 | Architecture | `brands/[id]/page.tsx` is 920 lines with 30+ state vars. Refactor into context + smaller components. |
| C2 | Responsive | Sidebar has no mobile breakpoint. Fixed width breaks mobile layouts entirely. |
| C3 | Responsive | CalendarView 7-column grid is unusable on mobile (53px per cell). |

### High-Priority Issues
| # | Category | Issue |
|---|----------|-------|
| H1 | State Mgmt | Zustand installed but unused. BrandDetailPage props pass-through should use context/store. |
| H2 | State Mgmt | BrandSwitcher CustomEvent only consumed by ContentStudioPage; other pages ignore it. |
| H3 | Architecture | ProductsTab receives 26 props. Extract product state into a hook or context. |
| H4 | a11y | CalendarView expanded-day overlay lacks focus trap, Escape handler, and dialog role. |
| H5 | a11y | Content creation dialog labels not programmatically associated with inputs. |
| H6 | Error Handling | 3+ API calls in BrandDetailPage use `.catch(() => {})`, hiding errors from users. |

### Medium-Priority Issues
| # | Category | Issue |
|---|----------|-------|
| M1 | a11y | Sidebar collapse button missing `aria-label` and `aria-expanded`. |
| M2 | a11y | Sidebar active link missing `aria-current="page"`. |
| M3 | a11y | KanbanBoard columns lack ARIA roles for screen readers. |
| M4 | a11y | Product table checkboxes have no labels or `aria-label`. |
| M5 | a11y | Multiple icon-only buttons lack `aria-label` (channel settings gear, gallery open, etc.). |
| M6 | a11y | CalendarView uses native drag-and-drop instead of `@dnd-kit` -- poor keyboard a11y. |
| M7 | Contrast | Status-only green dot for active brands -- no text companion. |
| M8 | Contrast | `text-muted-foreground/30` (30% opacity) on disabled channel icons may fail WCAG AA. |
| M9 | Contrast | `text-[8px]` and `text-[10px]` used extensively -- below recommended minimum size. |
| M10 | State | Multiple overlapping polling intervals in BrandDetailPage. |
| M11 | State | handleBulkProductActive fires N sequential API calls with no batching. |
| M12 | Forms | URL validation in BrandForm only on submit, no inline feedback. |
| M13 | Architecture | CalendarView uses inline overlay `div` instead of the project's Dialog component. |

### Low-Priority / Nice-to-Have
| # | Category | Issue |
|---|----------|-------|
| L1 | a11y | Product thumbnail `alt=""` should use product name. |
| L2 | a11y | Gallery images `alt=""` should use product name + index. |
| L3 | Consistency | Content dialog uses raw `<textarea>` and `<label>` instead of project's `Textarea`/`Label` components. |
| L4 | Architecture | BrandCard, KanbanBoard, and CalendarView each duplicate `CHANNEL_DISPLAY_NAMES` constant. Should import from `types/index.ts`. |
| L5 | Architecture | `CHANNEL_ICON_STYLED` is duplicated between `brands/[id]/page.tsx` and `OverviewTab.tsx`. |
| L6 | Architecture | `ChannelConfig` interface is redefined in 4 files. Should be a shared type. |
| L7 | DX | `ContentCalendarPage` silently swallows fetch errors. |

### What Is Done Well
1. **Loading states**: Skeleton components used consistently across all pages.
2. **Empty states**: Meaningful messages with CTAs on almost every list/grid.
3. **Error boundary**: Global `error.tsx` catches unhandled errors with retry.
4. **404 page**: Clean not-found page with navigation back to home.
5. **Auth flow**: AuthGate handles loading, unauthenticated, and token refresh gracefully.
6. **AbortController pattern**: Used in BrandDetailPage and ContentStudioPage to cancel stale requests.
7. **Theme support**: Full dark/light mode with proper CSS variables.
8. **Toast notifications**: Consistent use of Sonner for success/error feedback.
9. **Type safety**: Comprehensive TypeScript types in `types/index.ts`.
10. **API client**: Well-structured singleton with auth headers, HTTPS enforcement, and trailing-slash normalization.
11. **Form validation**: BrandForm validates URLs, file sizes, and file types.
12. **Confirm dialogs**: Destructive actions (delete brand, delete competitor) use ConfirmDialog.
