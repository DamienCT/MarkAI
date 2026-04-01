# MARKAI UI/UX VISUAL DESIGN AUDIT — MASTER IMPLEMENTATION PLAN

**Date:** 2026-04-01
**Application:** MarkAI — AI-Powered Marketing Operating System
**Stack:** Next.js 16.2.1 (App Router) | React 19 | Tailwind CSS 4.2.2 | Radix UI (shadcn/ui-style) | Lucide Icons | Recharts
**Styling:** CSS Variables (HSL) + Tailwind utility classes | Dark mode via next-themes
**Total Screens:** 21 distinct routes | **Total Components:** 50 files (18 UI primitives + 32 feature)

---

## TABLE OF CONTENTS

1. [Phase 0 — UI Reconnaissance & Inventory](#phase-0--ui-reconnaissance--inventory)
2. [Phase 1 — Layout & Spatial Architecture Audit](#phase-1--layout--spatial-architecture-audit)
3. [Phase 2 — Typography & Text Hierarchy Audit](#phase-2--typography--text-hierarchy-audit)
4. [Phase 3 — Component Design & Consistency Audit](#phase-3--component-design--consistency-audit)
5. [Phase 4 — Button, Action & Interactive Element Audit](#phase-4--button-action--interactive-element-audit)
6. [Phase 5 — Spacing, Alignment & Grid Audit](#phase-5--spacing-alignment--grid-audit)
7. [Phase 6 — Color, Contrast & Visual Hierarchy Audit](#phase-6--color-contrast--visual-hierarchy-audit)
8. [Phase 7 — Scroll Optimization & Information Density Audit](#phase-7--scroll-optimization--information-density-audit)
9. [Phase 8 — Responsive Design & Viewport Audit](#phase-8--responsive-design--viewport-audit)
10. [Phase 9 — Navigation, Wayfinding & Information Architecture Audit](#phase-9--navigation-wayfinding--information-architecture-audit)
11. [Phase 10 — Micro-Interactions, States & Feedback Audit](#phase-10--micro-interactions-states--feedback-audit)
12. [Phase 11 — Forms, Inputs & Data Entry Audit](#phase-11--forms-inputs--data-entry-audit)
13. [Phase 12 — Tables, Lists & Data Display Audit](#phase-12--tables-lists--data-display-audit)
14. [Phase 13 — Modals, Overlays, Toasts & Floating Elements Audit](#phase-13--modals-overlays-toasts--floating-elements-audit)
15. [Phase 14 — Icons, Images & Media Audit](#phase-14--icons-images--media-audit)
16. [Phase 15 — Dark Mode, Theming & Visual Modes Audit](#phase-15--dark-mode-theming--visual-modes-audit)
17. [Phase 16 — Animation, Transitions & Motion Audit](#phase-16--animation-transitions--motion-audit)
18. [Phase 17 — Empty, Loading, Error & Edge-Case States Audit](#phase-17--empty-loading-error--edge-case-states-audit)
19. [Phase 18 — Print & Export Rendering Audit](#phase-18--print--export-rendering-audit)
20. [Phase 19 — Iterative Re-Audit (Minimum 5 Passes)](#phase-19--iterative-re-audit-minimum-5-passes)
21. [Phase 20 — Final Report Compilation](#phase-20--final-report-compilation)

---

## PHASE 0 — UI RECONNAISSANCE & INVENTORY

### Step 0.1 — Screen & Route Inventory

Enumerate every screen. Read all route definitions from the App Router structure.

| # | Route | Page Component | Purpose | Auth | Data Dependency |
|---|-------|---------------|---------|------|-----------------|
| 1 | `/` | `src/app/page.tsx` | Mission Control — dashboard with stats, calendar, recent activity | Yes | `/api/v1/dashboard/stats`, `/api/v1/calendar/upcoming`, `/api/v1/agents/runs` |
| 2 | `/auth/signin` | `src/app/auth/signin/page.tsx` | Azure AD sign-in | No | None (OAuth redirect) |
| 3 | `/brands` | `src/app/brands/page.tsx` | Brand listing — all brands as cards | Yes | `/api/v1/brands` |
| 4 | `/brands/new` | `src/app/brands/new/page.tsx` | Create new brand — multi-field form + AI generation | Yes | None (form submission) |
| 5 | `/brands/[id]` | `src/app/brands/[id]/page.tsx` | Brand detail — tabbed interface (Overview, Channels, Logos, Intelligence, Products, Edit, Competitors, Performance) | Yes | `/api/v1/brands/:id` + tab-specific endpoints |
| 6 | `/content` | `src/app/content/page.tsx` | Content Studio — Kanban board + grid toggle | Yes | `/api/v1/content` |
| 7 | `/content/calendar` | `src/app/content/calendar/page.tsx` | Publishing calendar view | Yes | `/api/v1/calendar` |
| 8 | `/content/[id]` | `src/app/content/[id]/page.tsx` | Content editor — tabbed platform adaptations | Yes | `/api/v1/content/:id` |
| 9 | `/content/stage/[status]` | `src/app/content/stage/[status]/page.tsx` | Content filtered by pipeline stage | Yes | `/api/v1/content?status=` |
| 10 | `/approvals` | `src/app/approvals/page.tsx` | Approval queue — pending content reviews | Yes | `/api/v1/approvals` |
| 11 | `/intelligence` | `src/app/intelligence/page.tsx` | Intelligence dashboard — AI insights search | Yes | `/api/v1/intelligence` |
| 12 | `/intelligence/products` | `src/app/intelligence/products/page.tsx` | Product image management grid | Yes | `/api/v1/products` |
| 13 | `/intelligence/report/[id]` | `src/app/intelligence/report/[id]/page.tsx` | Detailed intelligence report (printable) | Yes | `/api/v1/intelligence/:id` |
| 14 | `/analytics` | `src/app/analytics/page.tsx` | Analytics dashboard — charts, heatmaps, engagement | Yes | `/api/v1/analytics/*` |
| 15 | `/learning` | `src/app/learning/page.tsx` | Learning & adaptations — AI model improvements | Yes | `/api/v1/learning` |
| 16 | `/providers` | `src/app/providers/page.tsx` | AI Providers — model configuration & selection | Yes | `/api/v1/providers/*` |
| 17 | `/prompts` | `src/app/prompts/page.tsx` | Prompt Lab — prompt version management | Yes | `/api/v1/prompts` |
| 18 | `/settings` | `src/app/settings/page.tsx` | General settings | Yes | `/api/v1/settings` |
| 19 | `/settings/users` | `src/app/settings/users/page.tsx` | Team/user management table | Yes | `/api/v1/users` |
| 20 | `/system` | `src/app/system/page.tsx` | System dashboard — health, queues, workflows | Yes | `/api/v1/system` |
| 21 | `/system/audit` | `src/app/system/audit/page.tsx` | Audit log viewer — paginated table | Yes | `/api/v1/system/audit-log` |

**Deliverable:** `./AUDIT_ARTIFACTS/ui/screen_inventory.md`

---

### Step 0.2 — Reusable Component Inventory

Enumerate every reusable component from the `src/components/` tree.

**UI Primitives** (`src/components/ui/` — 18 files):

| Component | File | Variants/Props | Used In |
|-----------|------|---------------|---------|
| Button | `ui/button.tsx` | variant: default, destructive, outline, secondary, ghost, link; size: default, sm, lg, icon | Nearly all screens |
| Card (Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent) | `ui/card.tsx` | — | Dashboard, Brands, Content, Analytics, System |
| Dialog (Dialog, DialogPortal, DialogOverlay, DialogClose, DialogTrigger, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription) | `ui/dialog.tsx` | — | Content creation, brand actions, confirmations |
| DropdownMenu (full set) | `ui/dropdown-menu.tsx` | — | Header user menu, notification dropdown, context menus |
| Table (Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption) | `ui/table.tsx` | — | Audit log, Users, Analytics, Approvals |
| Tabs (Tabs, TabsList, TabsTrigger, TabsContent) | `ui/tabs.tsx` | — | Brand detail, Content editor |
| Input | `ui/input.tsx` | — | All forms |
| Textarea | `ui/textarea.tsx` | — | Brand form, Content editor, Prompt lab |
| Label | `ui/label.tsx` | — | All forms |
| Select (full set) | `ui/select.tsx` | — | Filters, forms, brand switcher |
| Switch | `ui/switch.tsx` | — | Settings, provider toggles |
| Badge | `ui/badge.tsx` | variant: default, secondary, destructive, outline | Status indicators everywhere |
| Skeleton | `ui/skeleton.tsx` | — | Loading states |
| Avatar (Avatar, AvatarImage, AvatarFallback) | `ui/avatar.tsx` | — | Header, user lists, approvals |
| Separator | `ui/separator.tsx` | — | Dividers in menus, sections |
| ConfirmDialog | `ui/confirm-dialog.tsx` | — | Delete confirmations |
| SafeRender | `ui/safe-render.tsx` | — | XSS protection for user content |

**Layout Components** (`src/components/layout/` — 3 files):

| Component | File | Purpose |
|-----------|------|---------|
| Sidebar | `layout/Sidebar.tsx` | Collapsible nav (15 items), mobile hamburger, brand switcher |
| Header | `layout/Header.tsx` | Top bar: breadcrumbs, notifications, theme toggle, user dropdown |
| BrandSwitcher | `layout/BrandSwitcher.tsx` | Brand selector in sidebar |

**Feature Components** (32 files across 5 domains):

| Domain | Files | Key Components |
|--------|-------|----------------|
| Brand (`components/brand/`) | 13 | BrandCard, BrandForm, BrandOnboarding, CompetitorTracker, WorkflowStatus, + 8 tab components |
| Content (`components/content/`) | 7 | ContentCard, ContentEditor, KanbanBoard, KanbanBoardInner, CalendarView, ChannelPreview, PlatformMockups |
| Analytics (`components/analytics/`) | 4 | EngagementChart, EngagementChartInner, PerformanceGrid, PostingHeatmap |
| Approval (`components/approval/`) | 2 | ApprovalActions, ApprovalHistory |
| System (`components/system/`) | 3 | ServiceHealth, QueueDepth, WorkflowMonitor |

**Deliverable:** `./AUDIT_ARTIFACTS/ui/component_inventory.md`

---

### Step 0.3 — Design Token Extraction

Read all styling files and extract the full design system.

**Files to read:**
- `src/app/globals.css` — CSS variables, theme tokens, print styles
- `src/components/ui/button.tsx` — button variant CVA definitions
- `src/components/ui/badge.tsx` — badge variant definitions
- `src/lib/utils.ts` — `statusColor()` mapping, `cn()` utility

**Color Palette (CSS Variables, HSL):**

| Token | Light Mode | Dark Mode |
|-------|-----------|-----------|
| `--background` | `hsl(0 0% 100%)` | `hsl(222.2 84% 4.9%)` |
| `--foreground` | `hsl(222.2 84% 4.9%)` | `hsl(210 40% 98%)` |
| `--card` | `hsl(0 0% 100%)` | `hsl(222.2 84% 4.9%)` |
| `--primary` | `hsl(228 76% 59%)` | `hsl(228 76% 59%)` |
| `--primary-foreground` | `hsl(210 40% 98%)` | `hsl(210 40% 98%)` |
| `--secondary` | `hsl(210 40% 96.1%)` | `hsl(217.2 32.6% 17.5%)` |
| `--muted` | `hsl(210 40% 96.1%)` | `hsl(217.2 32.6% 17.5%)` |
| `--muted-foreground` | `hsl(215.4 16.3% 46.9%)` | `hsl(215 20.2% 65.1%)` |
| `--accent` | `hsl(210 40% 96.1%)` | `hsl(217.2 32.6% 17.5%)` |
| `--destructive` | `hsl(0 84.2% 60.2%)` | `hsl(0 62.8% 30.6%)` |
| `--border` | `hsl(214.3 31.8% 91.4%)` | `hsl(217.2 32.6% 17.5%)` |
| `--input` | `hsl(214.3 31.8% 91.4%)` | `hsl(217.2 32.6% 17.5%)` |
| `--ring` | `hsl(228 76% 59%)` | `hsl(228 76% 59%)` |

**Brand Colors (markai palette — static hex, not theme-aware):**
- `markai-50` through `markai-950`: indigo-blue gradient (`#f0f4ff` → `#1e3a8a`)

**Border Radius Scale:**
- `--radius`: `0.5rem` (8px)
- `--radius-sm`: `calc(0.5rem - 4px)` = 4px
- `--radius-md`: `calc(0.5rem - 2px)` = 6px
- `--radius-lg`: `0.5rem` = 8px

**Animations:**
- `accordion-down` / `accordion-up`: 0.2s ease-out
- Tailwind defaults: `animate-pulse`, `animate-spin`

**Typography:**
- Font family: Inter (Google Fonts via `next/font/google`)
- No custom type scale defined — relies on Tailwind defaults

**Spacing:**
- No custom spacing scale — uses Tailwind 4 defaults (4px base)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/design_tokens.md`

---

### Step 0.4 — Styling Approach Identification

| Aspect | Approach |
|--------|----------|
| Primary styling | Tailwind CSS 4.2.2 utility classes |
| Theme system | CSS custom properties (HSL) in `globals.css` + `.dark` class |
| Component variants | `class-variance-authority` (CVA) for Button, Badge |
| Class merging | `clsx` + `tailwind-merge` via `cn()` utility |
| UI primitives | Custom shadcn/ui-style components built on Radix UI |
| Dark mode | `next-themes` with class strategy, system preference default |
| Status colors | `statusColor()` in `utils.ts` — maps status strings to Tailwind classes |

**Potential findings to investigate:**
- Mixed approaches? Check for inline styles, raw CSS, or CSS modules alongside Tailwind
- Off-system color usage? `statusColor()` may use hardcoded Tailwind classes outside the CSS variable system
- markai-* brand colors are static hex — not theme-aware (won't adapt in dark mode)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/styling_approach.md`

---

### Step 0.5 — Visual Baseline Per Screen

For every screen identified in Step 0.1, read the full JSX/HTML template and associated styles.

**Action items (per screen):**
1. Read the page component file — understand every element rendered
2. Identify layout strategy (flex, grid, absolute)
3. Identify outermost container and its width behavior
4. Note scroll depth and primary action
5. Note data-dependent sections (what changes when empty/loading/error)

**Global layout structure** (from `src/app/layout.tsx`):
```
<div class="flex h-screen overflow-hidden">
  <Sidebar />                                    <!-- Left: collapsible, ~240px expanded / ~64px collapsed -->
  <div class="flex flex-1 flex-col overflow-hidden">
    <Header />                                   <!-- Top: fixed height -->
    <main class="flex-1 overflow-y-auto p-6">    <!-- Scrollable content area with 24px padding -->
      {children}
    </main>
  </div>
</div>
<Toaster />                                      <!-- Sonner: top-right -->
```

**Screens requiring detailed baseline reads (prioritized by complexity):**

| Priority | Screen | Reason |
|----------|--------|--------|
| P1 | Dashboard (`/`) | Most visible, complex layout with stats + calendar + activity |
| P1 | Content Studio (`/content`) | Kanban board is most complex interactive component |
| P1 | Brand Detail (`/brands/[id]`) | 8-tab interface, most feature-dense screen |
| P1 | Analytics (`/analytics`) | Charts, heatmaps, data grids — visual density |
| P2 | Content Editor (`/content/[id]`) | Complex form + platform previews |
| P2 | Approvals (`/approvals`) | Table + actions + history timeline |
| P2 | Prompt Lab (`/prompts`) | Code-like editing interface |
| P2 | AI Providers (`/providers`) | Model cards + configuration |
| P3 | Intelligence (`/intelligence`) | Search + results layout |
| P3 | Calendar (`/content/calendar`) | Date-based grid layout |
| P3 | System (`/system`) | Health cards + queue monitors |
| P3 | Settings + Users (`/settings`, `/settings/users`) | Forms + tables |
| P4 | All remaining screens | Lower complexity |

**Deliverable:** `./AUDIT_ARTIFACTS/ui/screen_baseline.md`

---

## PHASE 1 — LAYOUT & SPATIAL ARCHITECTURE AUDIT

### Scope

For each of the 21 screens, evaluate:

### Step 1.1 — Page Structure & Visual Hierarchy

**Per screen, answer:**
- Is the page title/heading immediately visible?
- Is the primary action above the fold?
- Is content importance proportional to space allocation?
- Does the user instantly know where they are (active nav, breadcrumbs)?

**Key areas of concern for MarkAI:**
- Dashboard: stat cards + calendar + recent activity — does the hierarchy guide the eye?
- Brand detail: 8 tabs — is the tab bar visually clear? Does it scroll horizontally on mobile?
- Content Studio: Kanban columns — do they waste space? Are columns equal width?

### Step 1.2 — Container Sizing

**Check for each screen:**
- Main content area: `flex-1 overflow-y-auto p-6` — is `p-6` (24px) appropriate at all viewports?
- On a 375px mobile screen, 24px left + 24px right = 48px consumed → only 327px content width
- At 1920px desktop: does content stretch too wide or is max-width applied?
- Are there screens with prose content exceeding 80ch line length?
- Are there forms stretching to full width on large screens?

### Step 1.3 — Sidebar Layout

**Audit:**
- Sidebar width: expanded (~240px) vs collapsed (~64px) — ratio to content
- At 1280px: sidebar 240px → content 1040px (reasonable)
- At 768px: sidebar hidden, mobile hamburger → full width content
- Brand switcher in sidebar — does it overflow on long brand names?
- 15 navigation items — does the sidebar scroll? Is scroll indicator visible?

### Step 1.4 — Header

**Audit:**
- Header height and stickiness
- Breadcrumb truncation behavior on small screens
- Notification dropdown — does it overflow viewport?
- User menu positioning

### Step 1.5 — Footer

**Audit:**
- No footer component identified — confirm no screen has floating/orphaned footer content

### Step 1.6 — Content Density

**Per screen, evaluate:**
- Dashboard: is the stats row above the fold? How many viewport heights to see all content?
- Content Studio Kanban: are cards compact enough to show meaningful content without excessive scrolling?
- Analytics: are charts taking appropriate vertical space?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/layout_audit.md`

---

## PHASE 2 — TYPOGRAPHY & TEXT HIERARCHY AUDIT

### Step 2.1 — Font Stack

**Known state:**
- Primary font: Inter (Google Fonts via `next/font/google`)
- No secondary/heading font
- Fallback: system font stack (from Next.js defaults)

**Audit:**
- Is Inter loaded efficiently? (next/font handles this — verify `font-display: swap`)
- Is the WOFF2 subset appropriate?
- Any additional fonts loaded via `<link>` or CSS `@import`?

### Step 2.2 — Font Size Hierarchy

**Action:** Extract every distinct `text-*` Tailwind class used across all 50 component files + 21 page files.

**Expected Tailwind scale:**
- `text-xs` (12px), `text-sm` (14px), `text-base` (16px), `text-lg` (18px), `text-xl` (20px), `text-2xl` (24px), `text-3xl` (30px), `text-4xl` (36px)

**Check:**
- Are there more than 8 distinct sizes in use?
- Is the heading hierarchy clear? (h1 > h2 > h3 at every screen)
- Is body text at least `text-sm` (14px)? Anything below 12px?
- Are page titles consistent size across all 21 screens?
- Are card titles consistent across Dashboard, Brands, Content, Analytics?
- Are label text sizes consistent across all forms?

### Step 2.3 — Font Weight Usage

**Check:**
- How many weights: 400 (regular), 500 (medium), 600 (semibold), 700 (bold)?
- Are headings consistently the same weight?
- Button text: `font-medium` (500) — consistent everywhere?
- Are there competing weights in the same context?

### Steps 2.4–2.7 — Line Height, Letter Spacing, Wrapping, Line Length

**Action per screen:**
- Measure line length of body text at 1440px desktop — flag anything over 80ch
- Check for `truncate` / `line-clamp` usage — is fallback (title attribute) present?
- Check for text overflow in cards, table cells, sidebar nav items
- Check if long brand names, content titles, or user names break layout

**Deliverable:** `./AUDIT_ARTIFACTS/ui/typography_audit.md`

---

## PHASE 3 — COMPONENT DESIGN & CONSISTENCY AUDIT

### Step 3.1 — Cross-Instance Consistency

**For each UI primitive, check every usage across all screens:**

| Component | Check |
|-----------|-------|
| Button | Same size/variant used for same action type across screens? Primary only 1 per section? |
| Card | Same padding, border-radius, shadow across Dashboard/Brands/Content/Analytics/System? |
| Badge | Same color for same status across Content Studio, Approvals, Calendar, System? |
| Table | Same row height, header style, cell padding in Audit Log, Users, Approvals? |
| Dialog | Same width, padding, close button position across all dialogs? |
| Input/Textarea | Same height, border, focus ring across all forms? |

### Step 3.2 — Card Consistency Audit

**Cards appear in:** Dashboard stats, Brand listing, Content grid, Analytics metrics, System health, Provider cards

**Check per location:**
- Inner padding value
- Border/shadow treatment
- Border-radius
- Title font-size and weight
- Do cards in the same grid have equal height?

### Step 3.3 — Badge/Status Color Consistency

**`statusColor()` in `utils.ts` maps statuses to Tailwind classes. Verify:**
- Every status string used in the app matches a mapping
- The same status always renders the same color (no overrides)
- Semantic consistency: green = success, red = error/destructive, yellow = warning everywhere

### Step 3.6 — Design Token Adherence

**Check all 50 component files + 21 page files for:**
- Raw hex/rgb colors instead of `var(--*)` tokens or Tailwind semantic classes
- Off-grid spacing values (anything not a multiple of 4px)
- Off-scale font sizes (raw `text-[13px]` instead of `text-sm`)
- Off-system border-radius values
- markai-* brand colors used in inappropriate contexts (they don't adapt to dark mode)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/component_consistency_audit.md` + `./AUDIT_ARTIFACTS/ui/design_token_consistency.md`

---

## PHASE 4 — BUTTON, ACTION & INTERACTIVE ELEMENT AUDIT

### Step 4.1 — Button Audit

**Button variants defined** (in `button.tsx` via CVA):
- `default`: `bg-primary text-primary-foreground hover:bg-primary/90`
- `destructive`: `bg-destructive text-destructive-foreground hover:bg-destructive/90`
- `outline`: `border border-input bg-background hover:bg-accent`
- `secondary`: `bg-secondary text-secondary-foreground hover:bg-secondary/80`
- `ghost`: `hover:bg-accent hover:text-accent-foreground`
- `link`: `text-primary underline-offset-4 hover:underline`

**Sizes:** `default` (h-10/40px), `sm` (h-9/36px), `lg` (h-11/44px), `icon` (h-10 w-10/40x40px)

**Audit per screen:**
- Is there only ONE `default` (primary) button per section?
- Are destructive actions (delete) using `destructive` variant and separated from constructive actions?
- Are button labels action-oriented verbs? ("Create Brand" not "Submit")
- Are icon-only buttons at least 36x36px? (icon size is 40x40px — good)
- Are buttons large enough for touch targets? (h-10 = 40px — meets 36px desktop, but not 44px mobile minimum)

**Concern:** `sm` size buttons are h-9 (36px) — borderline for mobile touch targets.

### Step 4.2 — Button State Audit

**Currently defined states** (from CVA base class):
- DEFAULT: styled
- HOVER: `hover:bg-primary/90` (opacity shift)
- FOCUS: `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`
- ACTIVE/PRESSED: **NOT DEFINED** — potential finding
- DISABLED: `disabled:pointer-events-none disabled:opacity-50`
- LOADING: **NOT DEFINED in CVA** — check if individual usages add spinner

**Missing:** Active/pressed state, loading spinner pattern — flag as findings.

### Steps 4.3–4.4 — Links & Interactive Affordance

**Check:**
- Are text links visually distinct from body text? (underline, color)
- Do all clickable cards have `cursor-pointer`?
- Are there elements that look clickable but aren't? (cards with hover but no click handler)
- Are there elements that are clickable but don't look it? (plain text acting as links)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/button_audit.md` + `./AUDIT_ARTIFACTS/ui/interactive_elements_audit.md`

---

## PHASE 5 — SPACING, ALIGNMENT & GRID AUDIT

### Step 5.1 — Spacing Grid

**Expected grid:** Tailwind 4 default = 4px base (4, 8, 12, 16, 20, 24, 32, 40, 48, 64)

**Audit for off-grid values:**
- Search all files for `p-[*]`, `m-[*]`, `gap-[*]` arbitrary values
- Search for inline `style={{ padding: ... }}` or `style={{ margin: ... }}`
- Any value not on the 4px grid is a finding

### Step 5.2 — Spacing Consistency

**Check per relationship:**
- Main content padding: `p-6` (24px) — consistent on all pages?
- Card inner padding — consistent across all card instances?
- Space between page title and content below
- Space between form label and input
- Space between form fields
- Space between icon and adjacent text
- Space between action buttons in groups

### Steps 5.3–5.7 — Alignment & Grid

**Check:**
- Horizontal alignment: icons + text vertically centered? (`items-center`)
- Table: numbers right-aligned? Text left-aligned? Actions right-aligned?
- Card grids: equal height cards? (`grid` with consistent row height)
- Last row of card grids: items don't stretch to fill (no `flex-grow` on last items)
- Kanban columns: equal width? Aligned tops?
- Dashboard stat cards: aligned values, aligned labels

**Deliverable:** `./AUDIT_ARTIFACTS/ui/spacing_alignment_audit.md`

---

## PHASE 6 — COLOR, CONTRAST & VISUAL HIERARCHY AUDIT

### Step 6.1 — Color Palette Audit

**Defined palette:** 12 semantic tokens (light + dark) + 11 brand colors (markai-*)

**Check:**
- Are there hex/rgb values used outside the palette in any component?
- Is `statusColor()` output consistent with the semantic token system?
- Are markai-* colors used appropriately? (They are static — do they work on dark backgrounds?)
- Are there clashing color combinations?

### Step 6.2 — Text Color Hierarchy

**Expected tiers:**
- Primary text: `text-foreground` (darkest)
- Secondary text: `text-muted-foreground` (medium)
- Tertiary text: lighter or `text-muted-foreground` with reduced opacity

**Check:** Are headings, body, labels, timestamps, and metadata using the correct tier consistently?

### Step 6.3 — Contrast Ratios (WCAG AA)

**Priority checks:**
- `--muted-foreground` on `--background`: light mode `hsl(215.4 16.3% 46.9%)` on white — calculate ratio
- `--primary` on `--primary-foreground`: blue on near-white — likely passes
- `--destructive` on `--destructive-foreground`: red on near-white — verify
- Dark mode: `--muted-foreground` (`hsl(215 20.2% 65.1%)`) on `--background` (`hsl(222.2 84% 4.9%)`) — verify
- Badge text on badge background for each variant
- Placeholder text contrast in inputs
- Disabled button text (50% opacity) — still readable?

### Step 6.4 — Visual Hierarchy Through Color

**Per screen:** Does the most important element (primary CTA, key metric, current status) have the strongest visual weight?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/color_contrast_audit.md`

---

## PHASE 7 — SCROLL OPTIMIZATION & INFORMATION DENSITY AUDIT

### Step 7.1–7.3 — Scroll Analysis

**For each screen at 1440x900 and 375x667:**

| Screen | Estimated Scroll Depth | Primary Action Above Fold? | Potential Waste |
|--------|----------------------|---------------------------|-----------------|
| Dashboard | Medium (stats + calendar + activity) | Likely yes | Check stat card height, section spacing |
| Brands listing | Low-Medium (card grid) | Yes (create button) | Check card grid gap |
| Brand detail | High (8 tabs, content varies) | Tab bar yes, tab content depends | Check tab content padding |
| Content Studio | Medium (Kanban fills viewport) | Yes | Column header height, card density |
| Content Editor | High (form + previews) | Depends on header size | Check form section spacing |
| Analytics | High (charts + grids + heatmap) | Partial | Chart heights may be excessive |
| Approvals | Low-Medium (table) | Yes | Row height, filter bar height |
| Settings/Users | Low-Medium | Yes | Table compactness |
| System | Medium | Yes | Health card density |

### Step 7.4–7.5 — Information Density

**Check:**
- Can dashboard stat cards be more compact? (3 separate cards → horizontal stat bar?)
- Can content cards in the grid show more items per viewport?
- Can Kanban card height be reduced while preserving key info?
- Are there filter bars above tables consuming 100px+ of vertical space?
- Can metadata in cards be compressed to fewer lines?

### Step 7.6 — Sticky Elements

**Check:**
- Table headers in Audit Log, Users — are they sticky on long lists?
- Tab bar in Brand Detail — does it stick when scrolling tab content?
- Kanban column headers — sticky?
- Header: sticky by layout structure (`flex h-screen` pattern) — verify consumption
- Total sticky height: Header (~56-64px) — acceptable

**Deliverable:** `./AUDIT_ARTIFACTS/ui/scroll_density_audit.md`

---

## PHASE 8 — RESPONSIVE DESIGN & VIEWPORT AUDIT

### Viewport Matrix

| Viewport | Width | Type | Purpose |
|----------|-------|------|---------|
| Mobile S | 320px | Mobile | Smallest supported |
| Mobile M | 375px | Mobile | iPhone SE/standard |
| Mobile L | 390px | Mobile | iPhone 14/15 |
| Tablet Portrait | 768px | Tablet | iPad portrait (md breakpoint) |
| Tablet Landscape | 1024px | Tablet | iPad landscape (lg breakpoint) |
| Desktop | 1280px | Desktop | Standard laptop (xl breakpoint) |
| Desktop L | 1440px | Desktop | Primary development viewport |
| Desktop XL | 1920px | Desktop | Full HD monitor |
| Ultrawide | 2560px | Desktop | Edge case |

### Step 8.1 — Mobile (320–390px)

**Critical checks:**
- Sidebar hidden → hamburger menu (confirmed `md:hidden` / `hidden md:flex`)
- Main content `p-6` (24px) — on 375px this leaves 327px content width. Consider reducing to `p-4` (16px) on mobile
- Touch targets: buttons at `h-10` (40px) — need `h-11` (44px) on mobile
- Kanban board: can horizontal columns work on mobile? Or should it stack?
- Card grids: `grid-cols-1` on mobile — verify
- Tables: horizontal scroll wrapper present?
- Dialog/modals: do they go full-screen or properly scale?
- Calendar view: is it usable on 375px?
- Brand detail tabs: do 8 tabs scroll horizontally?

### Step 8.2 — Tablet (768–1024px)

**Check:**
- Sidebar visible at `md` (768px)? Or still hidden?
- Grid layouts: `md:grid-cols-2` — appropriate?
- Content width with sidebar: 768 - 240 = 528px — tight for data tables
- At 1024px: should some grids go to 3 columns?

### Step 8.3 — Desktop (1280–1920px)

**Check:**
- Content max-width: is there one? Or does content stretch infinitely?
- At 1920px with sidebar: 1920 - 240 = 1680px content — text lines will be too long without max-width
- Card grids at 1920px: `lg:grid-cols-4` — appropriate? Or too many/few?

### Step 8.4 — Ultrawide (2560px)

**Check:** Does the layout still look intentional? Or does it stretch absurdly?

### Step 8.5 — Breakpoint Analysis

**Defined breakpoints (Tailwind 4 defaults):**
- `sm`: 640px
- `md`: 768px (primary layout shift — sidebar appears)
- `lg`: 1024px (grid column adjustments)
- `xl`: 1280px (rarely used — check if needed)

**Check:** Are there "in-between" viewport widths where layout breaks?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/responsive_audit.md`

---

## PHASE 9 — NAVIGATION, WAYFINDING & INFORMATION ARCHITECTURE AUDIT

### Step 9.1 — Primary Navigation

**Sidebar navigation (15 items):**
1. Dashboard (/)
2. Brands (/brands)
3. Content Studio (/content) — exact match
4. Calendar (/content/calendar)
5. Approvals (/approvals)
6. Intelligence (/intelligence) — exact match
7. Analytics (/analytics)
8. Learning (/learning)
9. AI Providers (/providers)
10. Prompt Lab (/prompts)
11. Product Images (/intelligence/products)
12. System (/system) — exact match
13. Audit Log (/system/audit)
14. Settings (/settings) — exact match
15. Users (/settings/users)

**Check:**
- 15 items is a lot — is grouping/sectioning needed? (e.g., "Content" group, "Admin" group)
- Active state highlighting: `isNavActive()` logic — verify edge cases
- Navigation order: is it logical? Most-used features first?
- Can a user reach any feature in 2-3 clicks?
- Are nav labels clear? ("Product Images" — is this expected under Intelligence?)

### Step 9.2–9.3 — Breadcrumbs & Page Titles

**Check:**
- Does every page have a visible title at the top?
- Are breadcrumbs passed to Header via `breadcrumbs` prop? Or are some pages missing them?
- Do breadcrumb labels match nav item names?
- Is browser tab title updated per page? (`metadata` in each page file or dynamic)

### Step 9.4 — Back Navigation

**Check:**
- Can users navigate back from Brand Detail → Brands listing?
- Can users navigate back from Content Editor → Content Studio?
- Are there dead-end pages? (modals that replace the page, or deep links with no back)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/navigation_audit.md`

---

## PHASE 10 — MICRO-INTERACTIONS, STATES & FEEDBACK AUDIT

### Steps 10.1–10.5 — State Coverage Per Component

**For every interactive element, verify these states are styled:**

| State | Button | Input | Link | Card | Tab | Select | Switch |
|-------|--------|-------|------|------|-----|--------|--------|
| Default | Yes | Check | Check | Check | Check | Check | Check |
| Hover | Yes (`/90`) | Check | Check | Check | Check | Check | Check |
| Focus | Yes (ring) | Check | Check | N/A | Check | Check | Check |
| Active | **Missing** | N/A | Check | N/A | Check | N/A | N/A |
| Disabled | Yes (50%) | Check | N/A | N/A | N/A | Check | Check |
| Selected | N/A | N/A | N/A | N/A | Check | Check | Check |
| Loading | **Custom** | N/A | N/A | Check (skeleton) | N/A | N/A | N/A |
| Error | N/A | Check (red border) | N/A | N/A | N/A | Check | N/A |

**Key focus areas:**
- Are focus rings visible on ALL focusable elements? (No `outline: none` without replacement)
- Does tab order follow visual order? (check for `tabIndex` manipulation)
- Are disabled elements still readable? (50% opacity on dark-on-dark may be invisible)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/states_feedback_audit.md`

---

## PHASE 11 — FORMS, INPUTS & DATA ENTRY AUDIT

### Forms Inventory

| Screen | Form | Complexity | Fields |
|--------|------|-----------|--------|
| `/brands/new` | BrandForm | High | Name, industry, tone, audience, guidelines, colors, AI-generate buttons |
| `/brands/[id]` (Edit tab) | EditBrandTab | High | Same as brand form (edit mode) |
| `/brands/[id]` (Channels tab) | ChannelsTab | Medium | Channel toggles + handle inputs per platform |
| `/content/[id]` | ContentEditor | High | Title, body, platform adaptations (tabbed) |
| `/prompts` | PromptForm (dialog) | Medium | Name, template, variables |
| `/settings` | SettingsForm | Low | Preferences, configuration |
| `/settings/users` | UserForm (dialog) | Low | Role selection, access grant |
| Various | ConfirmDialog | Low | Confirmation with optional reason |

### Steps 11.1–11.5 — Per-Form Audit

**Check per form:**
- Layout: single/multi-column appropriate for field count?
- Field widths: proportional to expected input? (zip code not full-width, email full-width)
- Labels: every input has a visible label (not just placeholder)?
- Label position: above input, consistent across all forms?
- Required field indicators: asterisk or "(required)" present?
- Error presentation: inline near field? Red border + text?
- Helper text: present for complex fields? Visually subordinate?
- Submit button: at bottom, primary variant, has loading state?
- Cancel option on edit forms?

**BrandForm-specific concerns:**
- AI generation buttons alongside inputs — clear visual hierarchy?
- Color picker integration — accessible? Keyboard navigable?
- Multi-step/wizard needed for the number of fields?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/forms_audit.md`

---

## PHASE 12 — TABLES, LISTS & DATA DISPLAY AUDIT

### Tables Inventory

| Screen | Table/List | Data |
|--------|-----------|------|
| `/system/audit` | Audit Log table | Timestamps, user, action, details |
| `/settings/users` | Users table | Name, email, role, status, last login |
| `/approvals` | Approval queue | Content title, brand, status, reviewer, actions |
| `/analytics` | Various data grids | Metrics, engagement data |
| `/content` | Content grid (alternative to Kanban) | Title, status, channel, date |
| `/brands/[id]` (Products tab) | Products table | Product name, SKU, status, image |

### Steps 12.1–12.2 — Per-Table Audit

**Check:**
- Column sizing: appropriate for content type? ID columns compact?
- Row height: 36-48px range? Or excessive padding?
- Alignment: numbers right-aligned? Text left? Actions right?
- Headers: sticky on vertical scroll?
- Hover state on rows?
- Empty state: what shows when 0 rows?
- Pagination: visible? Page size options? Current page indicator?
- Mobile: horizontal scroll or responsive stacking?

**Kanban Board-specific:**
- Column widths: equal?
- Card density: how many visible without scrolling per column?
- Drag-and-drop visual feedback
- Column scroll behavior (independent per column?)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/tables_lists_audit.md`

---

## PHASE 13 — MODALS, OVERLAYS, TOASTS & FLOATING ELEMENTS AUDIT

### Step 13.1 — Modal/Dialog Audit

**Dialog component** (`ui/dialog.tsx`): Radix-based with overlay + centered content.

**Check per dialog usage:**
- Width appropriate for content? (confirmation: 400-480px, form: 560-640px, complex: 800-960px)
- Max-height with internal scroll?
- Close button (X) in top-right?
- Overlay click dismisses?
- Escape key dismisses?
- Mobile adaptation: full-screen or bottom sheet?
- Action buttons clearly labeled and positioned?

**ConfirmDialog** (`ui/confirm-dialog.tsx`):
- Loading state during async confirmation?
- Destructive confirmations styled distinctly?

### Step 13.2 — Dropdown/Popover Audit

**Dropdown instances:** Header user menu, Header notifications, BrandSwitcher

**Check:**
- Viewport edge clipping? (notification dropdown near right edge)
- Item height: ≥36px for click targets?
- Currently selected item indicated?
- Max-height with scroll for long lists?

### Step 13.3 — Toast Audit

**Sonner** (top-right, rich colors, close button):

**Check:**
- Success = green, Error = red, Warning = yellow — consistent?
- Auto-dismiss duration appropriate?
- Multiple toasts stack cleanly?
- Toasts non-blocking?
- Mobile positioning appropriate?

### Step 13.4 — Tooltip Audit

**Radix Tooltip** (`@radix-ui/react-tooltip`):

**Check:**
- Present on icon-only buttons?
- Present on truncated text?
- Positioned correctly? (not clipped by viewport)
- Slight delay before showing? (~200-500ms)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/overlays_audit.md`

---

## PHASE 14 — ICONS, IMAGES & MEDIA AUDIT

### Step 14.1 — Icon Audit

**Library:** Lucide React (0.468.0) — confirmed single library.

**Check:**
- All icons from the same set? (outline vs solid mixing?)
- Consistent sizing: `16px` inline, `20-24px` standard, `32px+` feature?
- Aligned with adjacent text? (`items-center` consistently applied)
- Color consistent with text color in context?
- Decorative icons `aria-hidden`?
- Functional icon-only buttons have `aria-label`?

### Step 14.2 — Image Audit

**Image sources:** MinIO via `/api/v1/files/{path}`, remote patterns (hstgr.cloud, localhost:8000, minio:9000)

**Check:**
- `alt` text on all images?
- Aspect ratio maintained? (`object-fit: cover`/`contain`)
- Loading placeholder? (skeleton while loading)
- Broken image fallback?
- User-uploaded images constrained? (max-width, max-height)
- Product images, brand logos, content preview images — all handled?

### Step 14.3 — Logo Audit

**MarkAI branding:**
- Logo in sidebar header — appropriate size? Proper spacing?
- Logo quality at all sizes? (SVG preferred)
- Consistent placement across all pages

**Deliverable:** `./AUDIT_ARTIFACTS/ui/icons_images_audit.md`

---

## PHASE 15 — DARK MODE, THEMING & VISUAL MODES AUDIT

### Step 15.1 — Dark Mode Completeness

**Implementation:** `next-themes` with class strategy, system preference default.

**Check every screen and component in dark mode:**
- Any elements with hardcoded light colors? (`bg-white`, `text-black`, raw hex values)
- markai-* brand colors: static hex — do they work on dark backgrounds?
- Chart colors (Recharts): do they adapt to dark mode?
- Heatmap colors: appropriate for dark backgrounds?
- Image/logo contrast on dark background?
- Shadow visibility: shadows are less visible on dark — borders needed instead?
- Semantic color adjustment: `--destructive` dark mode is `hsl(0 62.8% 30.6%)` — very dark red, may have low contrast

**Specific concerns:**
- `statusColor()` returns Tailwind classes like `bg-green-100 text-green-800` — do these work in dark mode? Or do they need `dark:` variants?
- Calendar heatmap squares — visible in dark mode?
- Kanban drag overlay — styled for dark mode?

### Step 15.2 — Theme Toggle

**Check:**
- Toggle button discoverable? (Sun/Moon icon in Header)
- Transition smooth? (no flash of wrong theme)
- Preference persists across sessions? (localStorage via next-themes)
- System preference respected on first visit?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/dark_mode_theming_audit.md`

---

## PHASE 16 — ANIMATION, TRANSITIONS & MOTION AUDIT

### Step 16.1 — Transition Audit

**Currently defined:**
- Button hover: `transition-colors` (default duration 150ms)
- Sidebar collapse: `transition-all duration-200`
- Accordion: `0.2s ease-out`
- Radix components: `animate-in`/`animate-out` with fade + zoom + slide

**Check:**
- Are all hover effects transitioned? (not instant color jumps)
- Are dialog open/close animated? (fade + scale confirmed)
- Are page transitions present? (Next.js App Router has no built-in page transitions — instant route changes)
- Is sidebar expand/collapse smooth?
- Are dropdown menus animated in/out?
- Are tab content changes animated or instant?

### Step 16.2 — Animation Audit

**Check:**
- Skeleton loading: `animate-pulse` — appropriate speed?
- Spinner: `animate-spin` — used on loading buttons?
- Any distracting/excessive animations?
- Any autoplaying animations that should be stoppable?

### Step 16.3 — Layout Shift

**Check:**
- Images loading without aspect-ratio placeholder?
- Dynamic content (notifications, toasts) causing shift?
- Font swap causing layout shift? (next/font should prevent this)
- Async data loading pushing content down?

### Reduced Motion

**Check:** Is `prefers-reduced-motion` respected? Search for `motion-reduce:` Tailwind variants or `@media (prefers-reduced-motion)`.

**Deliverable:** `./AUDIT_ARTIFACTS/ui/animation_motion_audit.md`

---

## PHASE 17 — EMPTY, LOADING, ERROR & EDGE-CASE STATES AUDIT

### Step 17.1 — Empty States

**For every data-dependent section:**

| Screen / Section | Empty State Needed | Check |
|-----------------|-------------------|-------|
| Dashboard stats | Zero metrics | Does it show 0 or a message? |
| Dashboard calendar | No upcoming events | Empty calendar or message? |
| Dashboard recent activity | No agent runs | Empty state or blank? |
| Brands listing | No brands | "Create your first brand" CTA? |
| Content Studio Kanban | No content | Empty columns or message? |
| Content Calendar | No scheduled content | Empty calendar? |
| Approvals | No pending approvals | "All caught up" message? |
| Intelligence results | No results | Search empty state? |
| Analytics | No engagement data | Charts with no data? |
| Tables (Audit, Users) | No rows | Empty table state? |
| Products tab | No products | "Sync products" CTA? |
| Notifications dropdown | No notifications | "No new notifications"? |

### Step 17.2 — Loading States

**Check per screen:**
- Is there a skeleton/placeholder matching the eventual layout?
- Or is there a full-page spinner?
- Are loading states scoped to the right section? (one section loading doesn't block the whole page)
- Is the Skeleton component (`ui/skeleton.tsx`) used consistently?

### Step 17.3 — Error States

**Check per data fetch:**
- What shows when API call fails?
- Is there a retry option?
- Is the error message user-friendly? (not raw JSON or stack trace)

### Step 17.4 — Edge Cases

**Check:**
- Very long brand names (50+ characters) — overflow in sidebar, cards, breadcrumbs?
- Very long content titles — truncation in Kanban cards, tables?
- Many brands (50+) — BrandSwitcher dropdown handles long list?
- Many nav items (15) — sidebar scroll behavior?
- Special characters in names (emojis, unicode) — rendering?
- `null`/`undefined` displayed literally anywhere?

**Deliverable:** `./AUDIT_ARTIFACTS/ui/states_edge_cases_audit.md`

---

## PHASE 18 — PRINT & EXPORT RENDERING AUDIT

### Step 18.1 — Print Styles

**Current print CSS** (in `globals.css`):
```css
@media print {
  nav, aside, header, footer, [data-no-print], .no-print { display: none !important; }
  body { font-size: 12pt; color: #000 !important; background: #fff !important; }
  .print-break { page-break-before: always; }
  * { box-shadow: none !important; }
}
```

**Printable screens:**
- `/intelligence/report/[id]` — Intelligence reports (primary print target)
- `/analytics` — Potential for dashboard/report printing

**Check:**
- Is sidebar correctly hidden in print? (it's `nav` or `aside` — verify tag)
- Is header correctly hidden?
- Does report content fill the page width appropriately?
- Are charts/images rendered at appropriate print resolution?
- Are page breaks handled? (`.print-break` class used on long reports?)
- Are links showing URLs in print? Or just styled text?
- Are dark mode colors overridden for print? (`color: #000`, `background: #fff` — confirmed)

**Deliverable:** `./AUDIT_ARTIFACTS/ui/print_export_audit.md`

---

## PHASE 19 — ITERATIVE RE-AUDIT (MINIMUM 5 PASSES)

### Pass Schedule

| Pass | Focus | Lens |
|------|-------|------|
| **Pass 1** | Macro Review | Layout, container sizing, overall structure, major spacing, obvious visual problems |
| **Pass 2** | Typography & Color | Font sizes, weights, line heights, color consistency, contrast ratios, text hierarchy |
| **Pass 3** | Pixel-Level Precision | Alignment to the pixel, spacing grid adherence, border/shadow/radius consistency, subtle mismatches |
| **Pass 4** | States & Interactions | Every hover, focus, disabled, loading, empty, error, edge-case state |
| **Pass 5** | Mobile & Responsive | Every screen at every viewport, touch targets, scroll behavior, mobile nav, bottom-of-screen reachability |
| **Pass 6+** | Fresh Eyes | Only if new findings emerge in Pass 5 |

### Per-Pass Protocol

For each pass:
1. Re-examine every screen at every viewport
2. Re-read component styles
3. Ask: "Did I miss anything? Would a professional designer sign off on this?"
4. Log ALL new findings with full evidence (file, line, current CSS, recommended CSS)
5. If new findings > 0: continue to next pass
6. If new findings = 0 AND pass >= 5: proceed to Phase 20

**Deliverable:** `./AUDIT_ARTIFACTS/ui/reaudit_pass_N.md` (one per pass)

---

## PHASE 20 — FINAL REPORT COMPILATION

### Report Structure

The final report will be saved to: **`./UI_DESIGN_AUDIT_REPORT.md`**

**Sections:**

| # | Section | Content |
|---|---------|---------|
| 1 | Executive Summary | Total findings by severity, overall grade, top 5 issues, top 5 systemic patterns |
| 2 | Design System Assessment | Color, typography, spacing, component, token compliance grades |
| 3 | Critical Findings | Findings with severity = CRITICAL (exact values, file:line, recommended fix) |
| 4 | High Findings | Severity = HIGH |
| 5 | Medium Findings | Severity = MEDIUM |
| 6 | Low Findings | Severity = LOW |
| 7 | Informational | Suggestions and observations |
| 8 | Layout Report | Per-screen layout assessment |
| 9 | Typography Report | Font scale, hierarchy, line length analysis |
| 10 | Component Report | Per-component consistency findings |
| 11 | Button Report | Hierarchy, placement, sizing, state coverage |
| 12 | Spacing Report | Grid adherence, off-grid catalog, alignment |
| 13 | Color Report | Palette, off-palette, contrast failures |
| 14 | Scroll Report | Per-screen depth, density, above-the-fold |
| 15 | Responsive Report | Per-viewport findings, breakpoints |
| 16 | Navigation Report | Structure, active states, breadcrumbs |
| 17 | Forms Report | Layout, labels, errors, input sizing |
| 18 | Tables Report | Column sizing, row height, alignment |
| 19 | Overlays Report | Modal sizing, toast behavior, dropdowns |
| 20 | States Report | Empty/loading/error coverage |
| 21 | Dark Mode Report | Completeness, contrast, theme switching |
| 22 | Animation Report | Transitions, layout shift, reduced motion |
| 23 | Re-Audit Log | Pass summaries, finding trend |
| 24 | Phased Remediation Plan | A–J implementation phases with effort estimates |
| 25 | Screen Index | Every screen with finding count, severity, viewports |
| 26 | Metrics Dashboard | Compliance rates, coverage percentages |
| 27 | Quick Wins | Top 10 high-impact low-effort fixes |

### Remediation Phases

| Phase | Focus | Estimated Scope |
|-------|-------|-----------------|
| A | Critical & High — Visual Bugs | Broken layouts, invisible text, inaccessible elements |
| B | Scroll & Density Optimization | Wasted space, above-the-fold improvements |
| C | Spacing & Alignment Corrections | Grid adherence, pixel alignment, padding consistency |
| D | Typography Harmonization | Font scale cleanup, line height, weight consistency |
| E | Component Consistency | Duplicate components, variant standardization, token enforcement |
| F | Color & Contrast Fixes | WCAG failures, off-palette, semantic consistency |
| G | Button & Action Redesign | Hierarchy, placement, sizing, state coverage (active/loading) |
| H | Responsive Fixes | Mobile issues, touch targets, breakpoint gaps |
| I | State Coverage | Missing empty/loading/error/disabled states |
| J | Polish & Enhancement | Transitions, dark mode gaps, print, icon consistency, reduced motion |

### Severity Classification

| Severity | Definition | Examples |
|----------|-----------|---------|
| **CRITICAL** | Broken or unusable UI at any viewport | Content clipped/invisible, buttons unreachable, layout completely broken |
| **HIGH** | Significant visual defect or accessibility failure | WCAG contrast failure, missing focus indicators, overlapping elements |
| **MEDIUM** | Noticeable inconsistency or suboptimal design | Off-grid spacing, inconsistent card padding, wrong text hierarchy |
| **LOW** | Minor polish issue | 1-2px misalignment, slightly inconsistent border-radius, missing hover on one element |
| **INFO** | Suggestion/observation | "Dark mode would benefit from adjusted shadows", "Consider grouping nav items" |

---

## ARTIFACT OUTPUT STRUCTURE

```
./AUDIT_ARTIFACTS/
└── ui/
    ├── screen_inventory.md
    ├── component_inventory.md
    ├── design_tokens.md
    ├── styling_approach.md
    ├── screen_baseline.md
    ├── layout_audit.md
    ├── typography_audit.md
    ├── component_consistency_audit.md
    ├── design_token_consistency.md
    ├── button_audit.md
    ├── interactive_elements_audit.md
    ├── spacing_alignment_audit.md
    ├── color_contrast_audit.md
    ├── scroll_density_audit.md
    ├── responsive_audit.md
    ├── navigation_audit.md
    ├── states_feedback_audit.md
    ├── forms_audit.md
    ├── tables_lists_audit.md
    ├── overlays_audit.md
    ├── icons_images_audit.md
    ├── dark_mode_theming_audit.md
    ├── animation_motion_audit.md
    ├── states_edge_cases_audit.md
    ├── print_export_audit.md
    ├── reaudit_pass_1.md
    ├── reaudit_pass_2.md
    ├── reaudit_pass_3.md
    ├── reaudit_pass_4.md
    ├── reaudit_pass_5.md
    └── reaudit_pass_N.md  (if needed)

./UI_DESIGN_AUDIT_REPORT.md  (final deliverable)
```

---

## EXECUTION CHECKLIST

- [ ] **Phase 0:** Screen inventory (21 routes), component inventory (50 files), design tokens, styling approach, visual baseline
- [ ] **Phase 1:** Layout audit — all 21 screens, container sizing, sidebar, header, density
- [ ] **Phase 2:** Typography — font stack, size hierarchy, weight, line height, line length
- [ ] **Phase 3:** Component consistency — cross-instance checks, design token adherence
- [ ] **Phase 4:** Buttons — hierarchy, placement, sizing, labels, all 6 states, links, affordance
- [ ] **Phase 5:** Spacing — grid adherence, consistency, alignment precision, grid/flex layouts
- [ ] **Phase 6:** Color — palette audit, text hierarchy, contrast ratios (WCAG AA), visual hierarchy
- [ ] **Phase 7:** Scroll — depth per screen, waste identification, density optimization, sticky elements
- [ ] **Phase 8:** Responsive — 9 viewports per screen, breakpoint analysis, mobile touch targets
- [ ] **Phase 9:** Navigation — 15-item sidebar, active states, breadcrumbs, back navigation
- [ ] **Phase 10:** States — hover, focus, active, disabled, selected, loading for every interactive element
- [ ] **Phase 11:** Forms — 8+ forms, layout, labels, errors, helper text, submit/cancel
- [ ] **Phase 12:** Tables — 6+ tables/lists, columns, rows, alignment, empty states, pagination
- [ ] **Phase 13:** Overlays — dialogs, dropdowns, toasts (Sonner), tooltips
- [ ] **Phase 14:** Icons (Lucide), images (MinIO), logos, media
- [ ] **Phase 15:** Dark mode completeness, static brand colors, chart adaptation, theme toggle
- [ ] **Phase 16:** Transitions, animations, layout shift, reduced motion
- [ ] **Phase 17:** Empty/loading/error states for every data section, edge cases
- [ ] **Phase 18:** Print styles for intelligence reports
- [ ] **Phase 19:** Minimum 5 re-audit passes with progressive focus
- [ ] **Phase 20:** Final report compilation (27 sections) + phased remediation plan

---

## KEY FILES REFERENCE

| Purpose | File Path |
|---------|-----------|
| Global CSS / Theme tokens | `frontend/src/app/globals.css` |
| Root layout (shell) | `frontend/src/app/layout.tsx` |
| Providers wrapper | `frontend/src/app/providers-wrapper.tsx` |
| Sidebar | `frontend/src/components/layout/Sidebar.tsx` |
| Header | `frontend/src/components/layout/Header.tsx` |
| Brand Switcher | `frontend/src/components/layout/BrandSwitcher.tsx` |
| Button (CVA) | `frontend/src/components/ui/button.tsx` |
| Card | `frontend/src/components/ui/card.tsx` |
| Dialog | `frontend/src/components/ui/dialog.tsx` |
| Table | `frontend/src/components/ui/table.tsx` |
| Badge | `frontend/src/components/ui/badge.tsx` |
| Skeleton | `frontend/src/components/ui/skeleton.tsx` |
| Utilities (cn, statusColor) | `frontend/src/lib/utils.ts` |
| API client | `frontend/src/lib/api.ts` |
| Types | `frontend/src/types/index.ts` |
| Brand store (Zustand) | `frontend/src/stores/brand-store.ts` |
| Dashboard page | `frontend/src/app/page.tsx` |
| Content Studio | `frontend/src/app/content/page.tsx` |
| Kanban Board | `frontend/src/components/content/KanbanBoardInner.tsx` |
| Brand Detail | `frontend/src/app/brands/[id]/page.tsx` |
| Analytics | `frontend/src/app/analytics/page.tsx` |
| Charts | `frontend/src/components/analytics/EngagementChartInner.tsx` |
| Heatmap | `frontend/src/components/analytics/PostingHeatmap.tsx` |
