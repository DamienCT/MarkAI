# Universal Application — 5-Cycle Audit, Research, Implement & Ship Loop

## Objective

Execute a **5-cycle improvement loop** on this codebase. Each cycle follows four phases: **Audit → Research → Implement → Ship**. The goal is to systematically close every gap between what the application is supposed to do and what it actually does, modernise the stack to the latest stable patterns, achieve comprehensive test coverage, and produce a production-hardened, launch-ready product.

---

## Pre-Loop: Deep Orientation

Before starting Cycle 1, perform an exhaustive codebase walkthrough. Do not write a single line of code until orientation is complete.

1. **Map the entire repository** — Walk every directory. Read every config file, entry point, route definition, schema, model, migration, component, page, layout, middleware, utility, and README. Build a mental map of the full architecture.
2. **Identify the tech stack** — Record exact versions of every framework, library, runtime, database, cache, queue, and external service from package files and lockfiles. Note the language, build tool, bundler, linter, formatter, and test runner.
3. **Trace data flow end-to-end** — Pick the single most important user action in the app and trace it from UI interaction → API call → business logic → database write → response → UI update. Repeat for at least two more critical flows.
4. **Trace auth flow** — Map how authentication and authorisation work from login through to protected resource access. Note session management, token lifecycle, role enforcement, and middleware chains.
5. **Trace real-time flows** — If the app uses WebSockets, SSE, polling, or push notifications, trace every real-time channel from server emission to client handler. Note reconnection logic.
6. **Locate the source of truth for planned features** — Check for: TODO/FIXME/HACK/TEMP comments, feature flags, stub routes returning placeholder responses, skeleton UI components, config keys with no backing logic, commented-out code, roadmap files, spec docs, issue trackers, and any documentation describing features that should exist.
7. **Locate existing tests** — Find all test files. Note the test runner, assertion library, coverage tool, and what percentage of the codebase is covered. Identify which critical paths have tests and which do not.
8. **Check deployment configuration** — Review Dockerfiles, CI/CD pipelines, environment variable templates, infrastructure-as-code, reverse proxy config, process managers, and hosting setup.
9. **Identify external dependencies** — List every third-party API, SaaS service, cloud resource, and external system the app connects to. Note which have credentials configured and which are stubbed.

**Output the orientation as a structured summary: Architecture Overview, Tech Stack (with versions), Data Flows, Auth Architecture, Real-time Architecture, External Dependencies, Test Infrastructure, Deployment Setup, and Initial Observations.**

---

## Each Cycle (repeat 5×)

---

### Phase 1 — Audit

Produce a comprehensive audit report covering every category below. Be thorough and specific — vague findings like "needs improvement" are not acceptable. Every finding must describe the exact problem, its location in the codebase, and its impact.

#### A. Feature Completeness

Cross-reference the application's intended feature set against what is actually implemented:

- **Fully missing features** — Described in specs/docs/UI but no implementation exists.
- **Stub/placeholder features** — Routes that return hardcoded data, UI elements that are non-functional, screens that exist but do nothing, menu items pointing to empty pages, config keys with no backing logic, API endpoints declared but not wired to business logic, database tables/models with no CRUD operations.
- **Partially implemented features** — Logic exists but is incomplete, lacks edge-case handling, has hardcoded values where dynamic data should be used, or is missing one side of the stack (e.g., API exists but UI doesn't call it, or UI exists but API is missing).
- **"Coming soon" / deferred features** — Anything explicitly marked as not yet available. Determine if it should now be implemented.
- **Dead features** — Code that exists but is unreachable, feature-flagged off permanently, or no longer relevant.

#### B. Code Quality & Technical Debt

- **Dead code** — Unused imports, orphan files, unreachable functions, commented-out blocks, unused dependencies in package files.
- **Duplication** — Repeated logic that should be extracted into shared utilities, duplicated API calls, copy-pasted components with minor variations.
- **Naming & conventions** — Inconsistent naming conventions (camelCase vs snake_case mix, inconsistent file naming, inconsistent component patterns).
- **Type safety** — `any` types, missing type definitions, untyped function parameters, missing return types, type assertions that bypass safety.
- **Error handling** — Missing try/catch blocks, unhandled promise rejections, generic catch-all error handlers that swallow details, missing error boundaries in UI.
- **Hardcoded values** — Magic numbers, hardcoded strings (especially URLs, credentials, config values, feature flags) that should come from config or environment.
- **Dependency health** — Outdated dependencies, deprecated packages, packages with known vulnerabilities (`npm audit` / `pip audit` / equivalent), unused packages still in lockfile.

#### C. Security

| Category | What to Check |
|---|---|
| **Secrets management** | Are API keys, database credentials, tokens, or secrets hardcoded in source code, committed in `.env` files, logged to console, or exposed to the client? |
| **Authentication** | Are all protected routes and endpoints actually checking auth? Can unauthenticated requests reach protected resources? Are sessions/tokens properly validated, rotated, and expired? |
| **Authorisation** | Is role-based access enforced at the API/business logic level, not just the UI? Can a regular user access admin endpoints by calling them directly? |
| **Input validation** | Is every user input validated server-side? Are file uploads validated (type, size, content)? Are query parameters, path parameters, and request bodies validated against schemas? |
| **Injection** | SQL injection (raw queries with string interpolation), NoSQL injection, command injection, LDAP injection, XSS (unsanitised user content rendered as HTML), template injection. |
| **CSRF** | Are state-changing requests protected against CSRF? |
| **CORS** | Is CORS configured correctly — not `*` in production? |
| **Rate limiting** | Are critical endpoints (auth, API calls, file uploads, password resets) rate-limited? |
| **Data isolation** | Can one user access another user's data through any endpoint, parameter manipulation, or IDOR? |
| **Dependency vulnerabilities** | Run `npm audit` / `pip audit` / equivalent. Are there known CVEs in dependencies? |
| **Security headers** | Are standard security headers set (X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security, Content-Security-Policy, Referrer-Policy, Permissions-Policy)? |
| **Logging & exposure** | Are sensitive values (passwords, tokens, PII) logged or included in error responses? |
| **Cryptography** | Are passwords hashed with bcrypt/argon2 (not MD5/SHA1)? Are tokens cryptographically random? Is HTTPS enforced? |

#### D. UI/UX Quality

- **Loading states** — Is there a loading indicator for every async operation? Or do users stare at a blank screen?
- **Error states** — Is there a user-facing error message for every failure mode (network error, server error, validation error, auth expired, rate limited, service unavailable)?
- **Empty states** — Is there a helpful empty state for every list, table, feed, or search result that can be empty?
- **Responsive design** — Test at 375px, 390px, 412px, 768px, 1024px, 1440px. Check for: horizontal overflow, overlapping elements, unreadable text, unreachable buttons, broken layouts, images overflowing containers.
- **Mobile-specific** — Virtual keyboard handling (does content shift correctly?), touch targets (≥44×44px), hover-dependent functionality (broken on touch), safe area insets (notched devices), viewport height (`100dvh` vs `100vh`).
- **Accessibility** — Semantic HTML, ARIA labels on interactive elements, keyboard navigation, focus management, colour contrast ratios (WCAG AA), screen reader compatibility.
- **Consistency** — Are design tokens (colours, spacing, typography, border radii, shadows) consistent across all screens? Are there rogue inline styles or one-off values?
- **Animations & transitions** — Are they smooth (60fps)? Are they reducible for users who prefer reduced motion (`prefers-reduced-motion`)?
- **Dark mode** — If supported, does every screen render correctly in dark mode? Are there any elements with hardcoded light-mode colours?

#### E. Performance

- **Bundle size** — Run the build and analyse the output. Are there oversized bundles? Unused dependencies inflating size? Missing code splitting or lazy loading?
- **Render performance** — Are there unnecessary re-renders? Are expensive computations memoised? Are lists virtualised when they can grow large?
- **Database performance** — Are queries using proper indexes? Are there N+1 query patterns? Is there over-fetching (selecting all columns when only a few are needed)? Are there missing pagination or unbounded queries?
- **Caching** — Is there appropriate caching at the API, database, and client levels? Are cache invalidation patterns correct?
- **Network** — Are API calls deduplicated? Are there waterfalls (sequential calls that could be parallel)? Is there appropriate prefetching?
- **Assets** — Are images optimised? Are fonts loaded efficiently? Are static assets cached with proper headers?
- **Startup time** — How long from cold start to interactive? What is blocking?

#### F. Testing (CRITICAL CATEGORY)

- **Test existence** — Are there ANY tests? If not, this is the highest-priority finding.
- **Test coverage** — What percentage of the codebase is covered? Which critical paths are tested and which are not?
- **Test quality** — Do existing tests actually assert meaningful outcomes, or are they trivial/superficial? Do they test edge cases and error paths?
- **Test types present vs. missing:**
  - Unit tests (business logic, utilities, helpers)
  - Integration tests (API endpoints, database operations, auth flows)
  - Component tests (UI components render correctly, handle interactions)
  - End-to-end tests (critical user journeys from UI through to database)
  - Visual regression tests (screenshots at key viewports)
  - Performance tests (Lighthouse CI, load testing)
  - Security tests (auth bypass, injection, IDOR)
- **Test infrastructure** — Is the test runner configured? Is there a CI pipeline that runs tests? Is there a coverage reporting tool?
- **Flaky tests** — Are there tests that intermittently fail?

#### G. Documentation & Developer Experience

- **README** — Does it explain how to set up, run, test, and deploy the project? Is it accurate and current?
- **Environment setup** — Is there an `.env.example` with all required variables documented?
- **API documentation** — Are endpoints documented (OpenAPI/Swagger, or at minimum inline comments)?
- **Code comments** — Are complex business rules and non-obvious logic explained?
- **Contributing guide** — Are coding conventions, branch strategy, and PR process documented?
- **Architecture docs** — Is the high-level architecture documented anywhere?

#### H. Deployment & Infrastructure

- **Environment parity** — Does the development environment match production? Are there differences that could cause production-only bugs?
- **CI/CD** — Is there an automated pipeline? Does it run tests, lint, type-check, and build before deploy?
- **Monitoring** — Is there error tracking (Sentry, etc.)? Is there logging? Are there health check endpoints?
- **Backup & recovery** — Are database backups configured? Is there a recovery procedure?
- **Scaling** — Are there obvious bottlenecks that would break under increased load?
- **Environment variables** — Are all required env vars documented? Are there any missing in production that exist in development?

**Output format:** Markdown table with columns: Priority (Critical / High / Medium / Low), Category (A–H), Finding (specific description), Location (file path or area), Impact (what breaks or is at risk), Affected Platform (Desktop / Mobile / Both / Server).

---

### Phase 2 — Research (HEAVYWEIGHT)

**This phase is deliberately extensive. Do not skip or abbreviate it.** Stale patterns and outdated dependencies are technical debt. Before implementing any fix or feature, research the current state of the art.

#### 2A. Stack Freshness (MANDATORY for every cycle)

For EVERY major dependency in the project:

1. **Check the latest stable version** — Compare installed version vs. latest. Note the gap.
2. **Read the changelog** — Identify new features, breaking changes, deprecations, and security fixes between the installed version and latest.
3. **Evaluate upgrade path** — Is it a drop-in upgrade or does it require migration? What is the effort (low/medium/high)?
4. **Check for security advisories** — Run `npm audit` / `pip audit` / equivalent. Are there CVEs that require immediate action?
5. **Check for deprecated patterns** — Is the codebase using patterns that the framework/library has since deprecated? What is the modern replacement?

#### 2B. Architecture & Patterns

6. **Current best practices for the primary framework** — Search for "[framework] best practices [current year]". Read official documentation, blog posts, and conference talks. Are there new architectural patterns, hooks, APIs, or conventions that the codebase should adopt?
7. **Current best practices for the ORM/database layer** — Query optimisation, migration patterns, connection pooling, edge runtime support, new query builder features.
8. **Current best practices for authentication** — Session management, token rotation, OAuth flows, passwordless auth, passkeys — what is the recommended approach now?
9. **Current best practices for state management** — Has the state management ecosystem evolved? Are there simpler patterns, better middleware, or new tools?
10. **Current best practices for API design** — REST conventions, error response formats, pagination patterns, versioning, rate limiting middleware.

#### 2C. Frontend & Mobile Web

11. **Responsive design patterns [current year]** — Container queries, `dvh`/`svh`/`lvh` viewport units, modern CSS layout patterns (subgrid, `:has()`, `@layer`).
12. **Mobile web UX patterns** — Virtual keyboard handling (`visualViewport` API, `VirtualKeyboard` API), safe area insets, touch gesture libraries, PWA manifest updates, iOS Safari and Android Chrome quirks.
13. **Performance patterns** — `content-visibility: auto`, CSS `contain`, lazy loading, intersection observer patterns, image format (AVIF/WebP), font loading (`font-display: swap`, variable fonts).
14. **Accessibility standards** — Latest WCAG guidelines, ARIA patterns, focus management, screen reader testing tools.
15. **Animation & transitions** — View Transitions API, scroll-driven animations, `prefers-reduced-motion` patterns.

#### 2D. Testing (MANDATORY for every cycle)

16. **Testing framework best practices** — Search for "[test runner] best practices [current year]". Review recommended patterns for the specific testing tools in use.
17. **Integration testing patterns** — How to test API routes, database operations, auth flows, and external service integrations with the current stack.
18. **E2E testing tools** — Compare Playwright, Cypress, and alternatives. Which is recommended for the current stack? What are the latest features?
19. **Visual regression testing** — Tools and patterns for screenshot comparison at multiple viewports.
20. **Performance testing** — Lighthouse CI setup, Web Vitals monitoring, load testing tools.
21. **Security testing** — Automated security scanning tools, OWASP testing patterns, dependency audit automation.
22. **Test coverage tooling** — Coverage reporting, threshold enforcement, CI integration.

#### 2E. Security

23. **OWASP Top 10 [current year]** — Review the latest OWASP Top 10 list. Is the application vulnerable to any of these?
24. **Dependency vulnerability scanning** — Latest tools and CI integrations for automated vulnerability detection.
25. **Content Security Policy** — Research CSP best practices for the application's specific needs (inline scripts, external resources, etc.).
26. **Supply chain security** — Lockfile integrity, dependency pinning, provenance checking.

#### 2F. DevOps & Infrastructure

27. **Deployment best practices** — Current recommended patterns for the hosting platform in use.
28. **CI/CD pipeline patterns** — Latest GitHub Actions / GitLab CI / equivalent patterns for test → lint → build → deploy.
29. **Monitoring & observability** — Error tracking, structured logging, APM, alerting — what is the current recommended stack?
30. **Container & runtime updates** — Node.js LTS version, Python version, Docker base image updates, runtime security patches.

**For every research item, compile:**
| Field | Content |
|---|---|
| Current state | What the codebase does now |
| What changed | New version, pattern, or tool available |
| Recommended action | Specific change to make |
| Migration effort | Low / Medium / High |
| Source | Link to documentation or release notes |

---

### Phase 3 — Plan & Implement

Group audit findings into logical batches and implement in priority order:

#### Priority 1 — Critical Security & Stability
- Fix any exposed secrets or credentials
- Fix authentication and authorisation bypasses
- Fix input validation gaps
- Fix injection vulnerabilities (SQL, XSS, CSRF)
- Fix data isolation issues (IDOR)
- Apply critical dependency security patches
- Fix any crashes or data loss bugs

#### Priority 2 — Mobile & Responsive Fixes
- Fix all horizontal overflow issues at 375px–768px
- Fix virtual keyboard handling
- Fix touch targets (≥ 44×44px)
- Fix hover-dependent functionality for touch devices
- Fix viewport height issues (`100dvh`)
- Fix safe area insets for notched devices
- Fix modal/dialog sizing on mobile
- Fix navigation/sidebar behaviour on mobile

#### Priority 3 — Core Feature Completion
- Implement fully missing features (prioritised by user impact)
- Complete partially implemented features
- Wire stub/placeholder features to real logic
- Remove or properly defer "coming soon" items
- Clean up dead features and unreachable code

#### Priority 4 — Test Infrastructure & Coverage
- Set up test runner, assertion library, and coverage tool if not present
- Write unit tests for all business logic and utilities
- Write integration tests for all API endpoints
- Write component tests for critical UI components
- Write e2e tests for the top 5 critical user journeys
- Add visual regression tests at mobile viewports
- Set up CI pipeline to run all tests on every push
- Enforce minimum coverage threshold

#### Priority 5 — Performance Optimisation
- Fix bundle size issues (code splitting, lazy loading, tree shaking)
- Fix database query performance (indexes, N+1, over-fetching)
- Fix rendering performance (memoisation, virtualisation)
- Optimise assets (images, fonts, static files)
- Configure caching (client, API, database levels)
- Fix network waterfalls

#### Priority 6 — UX Polish
- Add missing loading states
- Add missing error states with helpful messages
- Add missing empty states
- Fix design token inconsistencies
- Fix accessibility issues (contrast, labels, keyboard nav, focus)
- Fix dark mode issues
- Add `prefers-reduced-motion` support

#### Priority 7 — Code Quality & Maintenance
- Remove dead code, unused imports, orphan files
- Extract duplicated logic into shared utilities
- Fix naming and convention inconsistencies
- Replace `any` types with proper type definitions
- Add error boundaries and proper error handling
- Replace hardcoded values with config/env vars
- Update outdated dependencies (non-breaking)

#### Priority 8 — Documentation & DevOps
- Update README with accurate setup, run, test, deploy instructions
- Create or update `.env.example` with all required variables
- Document API endpoints
- Add code comments to complex business logic
- Set up or improve CI/CD pipeline
- Set up error tracking and monitoring
- Configure database backups

**Implementation rules:**
- Follow existing project conventions. Do not introduce a new style unless the old one is clearly wrong.
- Use the project's ORM/query builder for all database operations — no raw queries with string interpolation.
- All new API endpoints must include input validation.
- All new features must include at least one test. All bug fixes must include a regression test.
- No hardcoded data where dynamic sources exist.
- No stubs, placeholders, or "TODO: implement later" — every change must be fully functional.
- Test every UI change at mobile (375px) and desktop (1440px) viewports minimum.
- Verify the app builds, starts, and all existing tests pass after every batch.
- Make small, incremental commits. Each commit should leave the app in a working state.

---

### Phase 4 — Test & Ship

#### 4A. Automated Checks
1. **Type check** — Run the type checker with strict mode. Zero errors.
2. **Lint** — Run the linter across the entire codebase. Zero warnings in CI-critical rules.
3. **Build** — Production build must succeed with no errors.
4. **Test suite** — Run all unit, integration, component, and e2e tests. 100% pass rate.
5. **Coverage** — Check coverage report. Note any critical paths below threshold.
6. **Security audit** — Run dependency vulnerability scanner. Address critical and high severity findings.

#### 4B. Manual Verification
7. **Desktop smoke test** — Open every primary screen at 1440px. Verify core user flows work.
8. **Mobile smoke test** — Open every primary screen at 375px and 390px. Verify:
   - No horizontal overflow
   - All buttons and links tappable
   - Navigation works (sidebar, menus, back buttons)
   - Forms are usable (inputs not obscured by keyboard)
   - Modals and dialogs fit within viewport
   - Content is readable (font sizes, contrast)
9. **Auth test** — Log in, access protected resources, log out. Verify session expiry works. Verify role-based access (if applicable).
10. **Error handling test** — Trigger at least 3 failure modes (network error, invalid input, expired session). Verify user-facing error messages appear.
11. **Performance spot check** — Check page load time, largest contentful paint, and interaction responsiveness on the most important page.

#### 4C. Ship
12. **Commit** — Use conventional commit format: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`, `perf:`, `security:`. One logical change per commit.
13. **Push to GitHub** — Push to the appropriate branch.
14. **Tag** — If this cycle represents a significant milestone, tag it (e.g., `v1.1.0-cycle3`).

---

## Cycle Progression Logic

| Cycle | Focus | Expected Outcome |
|---|---|---|
| **Cycle 1** | **Fix what's broken.** Security holes, crashes, mobile rendering issues, critical missing features, and zero-test-coverage bootstrapping. | No security vulnerabilities. No crashes. Mobile is usable. Test infrastructure exists. |
| **Cycle 2** | **Complete what's incomplete.** Wire all stub features, finish partial implementations, expand test coverage to all critical paths. | All core features work end-to-end. Critical paths have tests. |
| **Cycle 3** | **Elevate quality.** Performance optimisation, UX polish (loading/error/empty states), accessibility, responsive refinement, dependency upgrades. | Fast. Accessible. Polished. Dependencies current. |
| **Cycle 4** | **Harden for production.** Comprehensive test coverage, CI/CD pipeline, monitoring, documentation, edge-case handling, load testing. | High test coverage. CI/CD runs green. Documented. Monitored. |
| **Cycle 5** | **Final hardening.** Clean audit pass, remaining low-priority items, final dependency updates, production config review, launch checklist. | Clean audit. Launch-ready. No known critical or high issues. |

After completing Phase 4 of each cycle, **re-run Phase 1 (Audit) from scratch** on the updated codebase. The new audit must confirm previous findings are resolved and surface any new gaps introduced or newly visible.

---

## Completion Criteria

After 5 full cycles, produce a **final summary report**:

1. **Audit delta** — Side-by-side comparison of Cycle 1 audit findings count vs. Cycle 5 audit findings count, broken down by priority and category.
2. **Feature completion matrix** — Every intended feature marked: ✅ Implemented, ⚠️ Partial, ❌ Not implemented (with justification for any ❌).
3. **Test coverage report** — Total tests, coverage percentage, critical paths covered vs. uncovered.
4. **Security checklist** — Every security audit item marked pass/fail.
5. **Performance metrics** — Page load time, bundle size, Lighthouse scores (if web), before vs. after.
6. **Mobile quality** — Confirmation that all screens work at 375px, 390px, 412px, 768px with no rendering issues.
7. **Dependency versions** — Before vs. after for every major dependency.
8. **Total changes** — Commit count, files changed, lines added/removed per cycle.
9. **Known issues & intentional deferrals** — Anything left unresolved with clear justification and recommended timeline.
10. **Recommendations for Cycle 6+** — Prioritised list of what to tackle next.

---

## Rules

1. **Never skip research.** Every cycle must include a genuine research phase. Stale patterns are technical debt. The research phase exists to prevent you from implementing yesterday's solution to today's problem.
2. **Never skip testing.** Every new feature must have a test. Every bug fix must have a regression test. "It works when I try it" is not a test.
3. **Never leave stubs.** No placeholder implementations, no TODO comments in new code, no "coming soon" screens. Every change must be fully functional or not committed.
4. **Never break what works.** Verify the build, type check, lint, and full test suite pass after every implementation batch. If you break something, fix it before moving on.
5. **Always test mobile.** Every UI change must be verified at mobile viewports. Mobile is not an afterthought.
6. **Always validate security.** Every new endpoint must have auth checks and input validation. Every new user-facing input must be sanitised.
7. **Prefer small commits.** Each commit should be a single logical change that leaves the app in a working state. "Implemented everything" is not a commit message.
8. **Prefer CSS over JS for layout.** Use modern CSS (container queries, `dvh`, `clamp()`, `min()`/`max()`, grid, flexbox) before reaching for JavaScript layout solutions.
9. **Prefer existing conventions.** Match the project's existing patterns unless they are objectively wrong. Consistency beats personal preference.
10. **Use the ORM.** No raw database queries with string interpolation. Ever.
11. **Respect config.** No hardcoded credentials, URLs, feature flags, or magic numbers. Use environment variables and configuration files.
12. **Document decisions.** If you make a non-obvious architectural decision, leave a comment explaining why.
13. **Be honest in the audit.** Do not minimise findings to make the report look better. The audit exists to find problems, not to confirm that everything is fine.
