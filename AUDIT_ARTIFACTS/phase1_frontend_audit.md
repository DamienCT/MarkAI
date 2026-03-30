# MARKAI Frontend Audit - Phase 1

**Date:** 2026-03-30
**Scope:** Full file-by-file audit of `frontend/src/` (82 TypeScript/TSX files) + config files
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The frontend is a Next.js 16 + React 19 app using Radix UI, Tailwind CSS 4, Zustand, NextAuth, and Recharts. Overall code quality is **good** -- types are defined, error handling is present in most places, and loading/empty states are well covered. However, there are several **security issues** (access tokens in client-side types, sensitive channel config fields exposed), **performance issues** (missing memoization, redundant API calls, no lazy loading), and **reliability concerns** (missing cleanup, stale closure risks).

**Findings by severity:**
- CRITICAL: 2
- HIGH: 11
- MEDIUM: 19
- LOW: 12

---

## CRITICAL Findings

### C1. Access tokens stored in ChannelConfig types and exposed in client state
- **File:** `src/types/index.ts` lines 31-38, `src/app/brands/[id]/page.tsx` lines 91-95
- **Category:** Security
- **Description:** The `ChannelConfig` interface includes `access_token`, `api_key`, `refresh_token`, and `webhook_url` fields. These secrets are fetched from the backend, stored in React state (`channelConfigs`), and rendered in `<Input>` fields in `ChannelsTab.tsx`. If any XSS vector exists, these tokens are directly accessible. The backend should never send raw secrets to the frontend; it should send masked versions (e.g., `****abcd`).
- **Proposed fix:** Backend should return masked tokens (last 4 chars only). Add a separate "update token" flow where the user submits new tokens without seeing old ones. Frontend should never store raw API keys/access tokens in React state.

### C2. `any` type usage in BrandOnboarding violates strict TypeScript
- **File:** `src/components/brand/BrandOnboarding.tsx` line 65
- **Category:** Quality / Reliability
- **Description:** `api.get<any[]>(...)` bypasses all type checking. While this is a quality issue rather than a runtime bug, it can mask errors and is the only `any` usage in the codebase.
- **Proposed fix:** Replace with `api.get<Competitor[]>(...)` or a proper interface.

---

## HIGH Findings

### H1. No role-based access control on admin pages
- **File:** `src/app/settings/users/page.tsx`, `src/app/system/page.tsx`, `src/app/system/audit/page.tsx`, `src/app/settings/page.tsx`
- **Category:** Security
- **Description:** Admin-sensitive pages (Users & Roles, System Health, Audit Log, Settings) do not call `useRequireRole()`. Any authenticated user can access these pages and perform admin actions (grant access, change roles, modify settings, trigger workflows).
- **Proposed fix:** Add `useRequireRole("admin")` or `useRequireRole("manager")` at the top of each admin page component. The hook already exists in `src/lib/hooks.ts` but is never used anywhere.

### H2. XSS via `dangerouslySetInnerHTML`-equivalent: user-controlled `img src` attributes
- **File:** `src/components/content/AssetPreview.tsx` lines 21-22, `src/components/content/PlatformMockups.tsx` lines 52-54, `src/components/brand/tabs/LogosTab.tsx` line 64
- **Category:** Security
- **Description:** Multiple components render `<img src={url}>` or `<video src={url}>` where `url` comes from API data. If the backend stores a `javascript:` URL or an attacker-controlled URL, this could lead to phishing or data exfiltration. While `img src` doesn't execute JS in modern browsers, `video src` and malicious redirects remain a concern.
- **Proposed fix:** Validate all URLs on the frontend before rendering: ensure they start with `https://` or are relative paths. Add a `sanitizeUrl()` utility.

### H3. Hardcoded fallback API URL in production code
- **File:** `src/lib/api.ts` line 4
- **Category:** Security / Reliability
- **Description:** `const _rawApiUrl = process.env.NEXT_PUBLIC_API_URL || "https://api.markai.srv1191974.hstgr.cloud"` hardcodes a production URL as fallback. If the env var is missing during build, the app silently points to production. This could cause dev/staging environments to accidentally hit production APIs.
- **Proposed fix:** In development mode, throw an error or use `localhost:8000` as the fallback. Only use the production URL in the Dockerfile build arg.

### H4. Brand detail page is a 920-line god component with 30+ state variables
- **File:** `src/app/brands/[id]/page.tsx` (920 lines)
- **Category:** Quality / Performance
- **Description:** This single component manages ~30 `useState` hooks and ~15 `useCallback` functions. This causes unnecessary re-renders when any state changes (e.g., toggling a product re-renders the entire brand page). It's also extremely difficult to maintain.
- **Proposed fix:** Extract state into a custom hook (`useBrandDetail`) or use Zustand store. Move product management, image gallery, and channel config into their own state-managing components.

### H5. Multiple polling intervals without proper cleanup coordination
- **Files:** `src/app/brands/[id]/page.tsx` lines 238-250, 253-296; `src/components/layout/Header.tsx` lines 46-57; `src/components/brand/WorkflowStatus.tsx` lines 47-52
- **Category:** Performance / Reliability
- **Description:** The brand detail page can have up to 3 concurrent polling intervals (research poll, activation poll, pipeline poll) plus the header's notification poll. These are not coordinated and can cause API rate limiting. The activation poll at line 258 creates a new `setInterval` inside `useEffect` but the interval callback is async -- if the API is slow, multiple callbacks can overlap.
- **Proposed fix:** Use a single polling manager or reduce to one interval that fetches all needed data. For async interval callbacks, add a guard flag to prevent overlapping requests.

### H6. `fetchApprovals` called inside render cycle without stable reference
- **File:** `src/app/approvals/page.tsx` lines 18-19, 39
- **Category:** Reliability
- **Description:** `fetchApprovals()` is defined as a plain function inside the component (not wrapped in `useCallback`), then called in `useEffect` without being in the dependency array. It's also called after `handleAction` succeeds. ESLint would flag the missing dependency. The function closes over stale state.
- **Proposed fix:** Wrap `fetchApprovals` in `useCallback` and add it to the `useEffect` dependency array.

### H7. Audit log page `fetchEntries` not in useEffect dependency array
- **File:** `src/app/system/audit/page.tsx` lines 23-26
- **Category:** Bug
- **Description:** `useEffect` depends on `[actionFilter, resourceFilter, page]` but calls `fetchEntries()` which also uses `searchQuery` state. When `searchQuery` changes and the user clicks "Search", `fetchEntries` is called manually, but the `searchQuery` value used inside could be stale if called from the effect. Additionally, `fetchEntries` is not a stable reference.
- **Proposed fix:** Wrap `fetchEntries` in `useCallback` with proper dependencies, or include `searchQuery` in the effect dependency array.

### H8. `handleBulkProductActive` makes sequential API calls without parallelization
- **File:** `src/app/brands/[id]/page.tsx` lines 555-568
- **Category:** Performance
- **Description:** The bulk toggle iterates products with a `for...of` loop making sequential `await api.put()` calls. For 100+ products, this could take minutes and blocks the UI.
- **Proposed fix:** Use `Promise.all()` or `Promise.allSettled()` with batching (e.g., 10 at a time) for parallel execution.

### H9. No lazy loading for route-level pages
- **Files:** All page files under `src/app/`
- **Category:** Performance
- **Description:** All pages are eagerly loaded. Heavy pages like the intelligence report page (imports ReactMarkdown, many icons) and the brand detail page (920 lines) add to initial bundle size. Next.js App Router supports `dynamic()` imports.
- **Proposed fix:** Use `next/dynamic` with `ssr: false` for heavy client components like the intelligence report page, content calendar, and kanban board.

### H10. Recharts imported eagerly in analytics page
- **File:** `src/components/analytics/EngagementChart.tsx`, `src/app/analytics/page.tsx`
- **Category:** Performance
- **Description:** Recharts is a large library (~200KB) imported eagerly. It's only used on the analytics page but contributes to the main bundle.
- **Proposed fix:** Dynamically import `EngagementChart` and `PostingHeatmap` components using `next/dynamic`.

### H11. Calendar expanded day overlay is a custom modal without accessibility
- **File:** `src/components/content/CalendarView.tsx` lines 241-316
- **Category:** Quality / Accessibility
- **Description:** The expanded day view uses a custom `div` overlay instead of a proper Dialog/Modal component. It lacks: focus trapping, Escape key handling, `role="dialog"`, `aria-modal`, and screen reader announcements. Clicking the backdrop closes it but keyboard users cannot dismiss it.
- **Proposed fix:** Replace with Radix UI `Dialog` component (already imported elsewhere) for proper accessibility.

---

## MEDIUM Findings

### M1. Duplicate `ALL_CHANNELS` and `CHANNEL_DISPLAY_NAMES` constants
- **Files:** `src/types/index.ts` lines 11-25, `src/app/brands/[id]/page.tsx` lines 31-56, `src/components/content/KanbanBoard.tsx` lines 27-36
- **Category:** Quality
- **Description:** Channel names and display names are defined in 3+ places. Changes in one place won't propagate.
- **Proposed fix:** Import from `@/types` everywhere. Remove duplicates.

### M2. `brand.status` dependency in useEffect without `brand` in deps
- **File:** `src/app/brands/[id]/page.tsx` line 471
- **Description:** `useEffect` depends on `[brand?.status]` but accesses `brand` object inside. If `brand` changes without `status` changing, the effect won't re-run but would use stale `brand` reference.
- **Proposed fix:** Add `brand` to the dependency array or use `brand?.status` consistently.

### M3. Missing `AbortController` cleanup on several pages
- **Files:** `src/app/page.tsx`, `src/app/analytics/page.tsx`, `src/app/intelligence/page.tsx`, `src/app/learning/page.tsx`
- **Category:** Reliability
- **Description:** These pages fetch data in `useEffect` but don't abort requests on unmount. If the user navigates away during a fetch, the state setter will be called on an unmounted component. React 19 handles this more gracefully than older versions, but it's still a memory leak.
- **Proposed fix:** Add AbortController pattern (already used in brand detail page and content studio).

### M4. `ConfirmDialog` closes before async `onConfirm` completes
- **File:** `src/components/ui/confirm-dialog.tsx` lines 46-51
- **Category:** Bug
- **Description:** `onConfirm()` is called synchronously and `onOpenChange(false)` is called immediately after. If `onConfirm` is async (like `handleDelete`), the dialog closes before the operation completes. No loading state is shown.
- **Proposed fix:** Make `onConfirm` awaitable, add loading state, close dialog only after completion.

### M5. `AssetPreview` Dialog missing `DialogTitle` for accessibility
- **File:** `src/components/content/AssetPreview.tsx` line 29
- **Category:** Quality / Accessibility
- **Description:** The Dialog used for zooming assets has no `DialogTitle`, which violates ARIA requirements for dialog elements.
- **Proposed fix:** Add a visually hidden `DialogTitle` using `sr-only` class.

### M6. PlatformMockups Dialog missing `DialogTitle`
- **File:** `src/components/content/PlatformMockups.tsx` line 69
- **Category:** Quality / Accessibility
- **Description:** Same as M5 -- no `DialogTitle` in the enlarge dialog.
- **Proposed fix:** Add a visually hidden `DialogTitle`.

### M7. BrandSwitcher fetches brands independently from other components
- **File:** `src/components/layout/BrandSwitcher.tsx` lines 20-32
- **Category:** Performance
- **Description:** The BrandSwitcher fetches `/api/v1/brands` on mount. Multiple other pages also fetch brands (Content Studio, Analytics, System). This means the brands list is fetched 2-3 times on page load.
- **Proposed fix:** Use a shared Zustand store or React Query cache for brands data.

### M8. `window.dispatchEvent(new CustomEvent("brand-changed"))` is a fragile pattern
- **Files:** `src/components/layout/BrandSwitcher.tsx` line 38, `src/app/content/page.tsx` line 84
- **Category:** Quality
- **Description:** Using `CustomEvent` on `window` for cross-component communication is fragile and not type-safe. Components must manually add/remove event listeners, and there's no TypeScript checking on the event payload.
- **Proposed fix:** Use a Zustand store for selected brand state, or React Context.

### M9. Notification polling every 30s regardless of tab visibility
- **File:** `src/components/layout/Header.tsx` line 50
- **Category:** Performance
- **Description:** Notification polling runs every 30 seconds even when the browser tab is in the background, wasting bandwidth.
- **Proposed fix:** Use `document.visibilityState` to pause polling when the tab is hidden.

### M10. Promise.allSettled used but catch block is unreachable
- **Files:** `src/app/page.tsx` line 39, `src/app/analytics/page.tsx` line 108
- **Category:** Quality
- **Description:** `Promise.allSettled` never throws, so the outer `catch` block is dead code. This is harmless but misleading.
- **Proposed fix:** Remove the unreachable `catch` block or switch to `Promise.all` if you want the catch to work.

### M11. No input length limits on form fields
- **Files:** `src/components/brand/BrandForm.tsx`, `src/app/content/page.tsx` (new content dialog), `src/components/brand/CompetitorTracker.tsx`
- **Category:** Security
- **Description:** Text inputs and textareas have no `maxLength` attributes. A malicious user could submit extremely long strings that may cause backend issues or UI overflow.
- **Proposed fix:** Add reasonable `maxLength` attributes (e.g., 200 for names, 5000 for descriptions).

### M12. `products.length` check in brands page onboarding calculation may be stale
- **File:** `src/app/brands/[id]/page.tsx` lines 486, 203
- **Category:** Bug
- **Description:** `onboardingProgress` is calculated using `products.length` and `competitors.length` from state. However, products are fetched in a separate `.then()` chain that doesn't guarantee it completes before `onboardingProgress` is first evaluated. This means the first render may show 0 products even if products exist.
- **Proposed fix:** Add a `loadingProducts` check to the onboarding progress calculation, or wait for all fetches before computing progress.

### M13. `useRequireRole` hook never used anywhere
- **File:** `src/lib/hooks.ts`
- **Category:** Quality
- **Description:** The role-checking hook is implemented but never imported or used by any page. This means role-based access control exists only as dead code.
- **Proposed fix:** Apply it to pages that need role restrictions (see H1).

### M14. `fetchApprovals` called twice on approval action
- **File:** `src/app/approvals/page.tsx` lines 36-39
- **Category:** Performance
- **Description:** After approving/rejecting, the code first filters the item from state (`setApprovals(prev => prev.filter(...))`) then immediately calls `fetchApprovals()` which refetches the entire list. The optimistic update is immediately overwritten.
- **Proposed fix:** Either do optimistic update only, or remove the filter and just refetch.

### M15. `signal` used after abort in brand detail page
- **File:** `src/app/brands/[id]/page.tsx` line 203
- **Category:** Bug
- **Description:** After `abortRef.current?.abort()` and creating a new controller on line 173, the code on line 203 uses `{ signal }` which references the new controller. However, the `.then()` chain on line 203 (products fetch) and line 205 (pipeline runs fetch) don't have `.catch()` handlers for AbortError specifically -- they use empty `.catch(() => {})` which silently swallows all errors including real network failures.
- **Proposed fix:** Add specific AbortError handling or at minimum log non-abort errors.

### M16. `bcCompany` select allows empty string as value
- **File:** `src/components/brand/BrandForm.tsx` line 588
- **Category:** Bug
- **Description:** The `Select` component has `value={bcCompany ?? ""}`. When `bcCompany` is null, it passes empty string as value. Radix Select may not handle empty string value correctly as a "no selection" state.
- **Proposed fix:** Use a sentinel value like `"__none__"` or handle the null case in onValueChange.

### M17. Large bundle: `lucide-react` icons imported individually but from barrel export
- **Files:** Most components
- **Category:** Performance
- **Description:** While individual icon imports look tree-shakeable (`import { ArrowLeft } from "lucide-react"`), the barrel export from lucide-react can still include unused code depending on bundler configuration. With 50+ unique icons used across the app, this is likely already optimized by Next.js, but worth verifying bundle size.
- **Proposed fix:** Verify with `@next/bundle-analyzer` that tree shaking is working. Consider `lucide-react/icons/*` deep imports if bundle is large.

### M18. `engagement_rate * 100` display inconsistency
- **Files:** `src/app/analytics/page.tsx` line 180, `src/components/brand/tabs/OverviewTab.tsx` line 383, `src/components/brand/tabs/PerformanceTab.tsx` line 33
- **Category:** Quality
- **Description:** Engagement rate is sometimes displayed as `(rate * 100).toFixed(2)%` and sometimes as `(rate * 100).toFixed(1)%` or `(rate * 100).toFixed(0)%`. Inconsistent precision across pages.
- **Proposed fix:** Create a shared `formatPercentage(rate: number, decimals = 2)` utility.

### M19. `next-auth` v4 with Next.js 16 / React 19 compatibility
- **File:** `package.json` line 31
- **Category:** Reliability
- **Description:** `next-auth@4.24.11` is designed for Next.js 13-14. Next.js 16 with React 19 may have subtle incompatibilities. The project should either upgrade to `next-auth@5` (now Auth.js) or verify compatibility.
- **Proposed fix:** Test thoroughly or migrate to `next-auth@5` / `@auth/nextjs`.

---

## LOW Findings

### L1. `parseError` variable unused in api.ts catch block
- **File:** `src/lib/api.ts` line 82
- **Category:** Quality
- **Description:** The catch block uses `catch (parseError)` but the variable `parseError` is never used.
- **Proposed fix:** Change to `catch { ... }` (already done in other catch blocks in the same file, but this one was missed historically -- actually this uses the correct catch-without-binding pattern. On re-inspection, this is fine in the current code).

### L2. `statusColor` import unused in some files
- **File:** `src/app/intelligence/products/page.tsx` line 10
- **Category:** Quality
- **Description:** `statusColor` is imported but never used in the ProductsPage component.
- **Proposed fix:** Remove unused import.

### L3. Sign-in page duplicates AuthGate login UI
- **Files:** `src/app/auth/signin/page.tsx`, `src/app/providers-wrapper.tsx` lines 33-55
- **Category:** Quality
- **Description:** The sign-in page and the AuthGate component have nearly identical login card UI. If one is updated, the other may be forgotten.
- **Proposed fix:** Extract shared login card component.

### L4. `useParams().id as string` unsafe cast
- **Files:** `src/app/brands/[id]/page.tsx` line 114, `src/app/content/[id]/page.tsx` line 19, `src/app/intelligence/report/[id]/page.tsx` line 272
- **Category:** Reliability
- **Description:** `params.id` is cast to `string` without validation. If the route somehow receives an array or undefined, this would pass a wrong value to API calls.
- **Proposed fix:** Add validation: `const brandId = Array.isArray(params.id) ? params.id[0] : params.id;` or use a type guard.

### L5. `Dockerfile` does not copy `.env` or `.env.local`
- **File:** `Dockerfile`
- **Category:** Quality
- **Description:** This is actually correct (secrets should not be baked into images), but the `NEXT_PUBLIC_API_URL` build arg default means the app will work even without proper env configuration, which can mask misconfigurations.
- **Proposed fix:** Document that `NEXT_PUBLIC_API_URL` must be set via build arg.

### L6. `formatDuration` returns "N/A" for 0ms
- **File:** `src/app/intelligence/report/[id]/page.tsx` line 251
- **Category:** Bug (minor)
- **Description:** `if (!ms)` is falsy for both `null` and `0`. A duration of 0ms would show "N/A" instead of "0ms".
- **Proposed fix:** Use `if (ms == null)` instead.

### L7. Calendar drag-and-drop uses native HTML drag API, not dnd-kit
- **File:** `src/components/content/CalendarView.tsx` lines 110-119
- **Category:** Quality
- **Description:** The CalendarView uses native `draggable` and `onDragStart`/`onDrop` events, while the KanbanBoard uses `@dnd-kit`. Two different drag systems in the same app area is inconsistent.
- **Proposed fix:** Consider using `@dnd-kit` for the calendar as well for consistency and better touch support.

### L8. `date-fns` version 4 breaking changes
- **File:** `package.json` line 28
- **Category:** Reliability
- **Description:** `date-fns@4.1.0` has breaking changes from v3. Verify all date-fns imports work correctly (the code appears to use v4-compatible imports).
- **Proposed fix:** No action needed if tests pass; just document the dependency.

### L9. `CHANNEL_ICON_STYLED` in OverviewTab uses `<span>` placeholder icons
- **File:** `src/components/brand/tabs/OverviewTab.tsx` lines 21-30
- **Category:** Quality
- **Description:** The fallback `CHANNEL_ICON_STYLED` constant uses empty `<span>` elements instead of actual icons. This constant is only used as a fallback since the parent passes the real icons, but it's confusing dead code.
- **Proposed fix:** Remove the local constant since `channelIconStyled` prop always provides the real icons.

### L10. Missing `key` prop uniqueness concern in heatmap
- **File:** `src/components/analytics/PostingHeatmap.tsx` line 56
- **Category:** Quality
- **Description:** Inner loop key uses `hour` alone. Combined with outer key `day`, React can distinguish them, but the inner `key={hour}` could be more explicit.
- **Proposed fix:** Use `key={\`\${dayIndex}-\${hour}\`}` for clarity.

### L11. `@tailwindcss/postcss` v4 may not support all Tailwind v3 utilities
- **File:** `postcss.config.mjs`
- **Category:** Reliability
- **Description:** The project uses Tailwind CSS v4 with the new PostCSS plugin. Some v3 utilities like `bg-linear-to-br` (used in BrandCard and other files) are v4 syntax. Verify all utilities compile correctly.
- **Proposed fix:** Run a build and verify no CSS warnings.

### L12. No error boundary for individual page sections
- **Files:** All page components
- **Category:** Reliability
- **Description:** While a global `error.tsx` exists at the app level, individual sections (e.g., the analytics chart, kanban board) don't have error boundaries. A rendering error in one section crashes the entire page.
- **Proposed fix:** Add error boundaries around complex sections like charts, drag-and-drop boards, and markdown renderers.

---

## Config File Review

### `package.json`
- Dependencies are up to date. No known vulnerable versions detected.
- `zustand@5.0.3` is installed but not used anywhere in the codebase. Consider removing.

### `next.config.ts`
- `images.unoptimized: true` disables Next.js image optimization. This is likely intentional for the standalone Docker build but means images are served at original size with no WebP conversion.
- `images.remotePatterns` only allows `*.hstgr.cloud`. If the app ever serves images from other domains (e.g., social media avatars, MinIO), they'll be blocked by `next/image`.

### `tsconfig.json`
- `strict: true` is enabled -- good.
- `target: "ES2017"` could be bumped to `ES2020` or later for modern browser support.

### `eslint.config.mjs`
- Uses Next.js recommended + TypeScript configs. No custom rules.

### `Dockerfile`
- Well-structured multi-stage build. Uses non-root user. Good.
- `--legacy-peer-deps` flag suggests dependency conflicts that should be resolved.

---

## Summary of Recommended Priority Actions

1. **CRITICAL:** Remove raw access tokens from frontend API responses (C1)
2. **HIGH:** Add `useRequireRole()` to admin pages -- Users, Settings, System, Audit (H1)
3. **HIGH:** Add URL sanitization for user-provided/API-provided URLs (H2)
4. **HIGH:** Break up the 920-line brand detail page (H4)
5. **HIGH:** Coordinate polling intervals and add overlap protection (H5)
6. **MEDIUM:** Add AbortController to all data-fetching useEffects (M3)
7. **MEDIUM:** Replace `CustomEvent` brand switching with Zustand store (M8)
8. **MEDIUM:** Share brands data across components (M7)
9. **MEDIUM:** Add `maxLength` to form inputs (M11)
10. **MEDIUM:** Fix ConfirmDialog to await async onConfirm (M4)
