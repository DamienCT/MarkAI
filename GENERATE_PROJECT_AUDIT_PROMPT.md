# CODEBASE-AWARE AUDIT PROMPT GENERATOR

## AGENT DIRECTIVE — READ EVERYTHING, THEN WRITE THE DEFINITIVE AUDIT DOCUMENT FOR THIS EXACT PROJECT

---

> **YOUR MISSION:** You will perform a complete, silent reconnaissance of this entire repository — every file, every dependency, every pattern, every flaw. You will then distill everything you learned into a single, hyper-specific audit prompt document tailored exclusively to THIS codebase. The output document must be so detailed, so precisely targeted, and so rich with project-specific context that a separate AI coding agent — one that has never seen this repo before — could pick it up, execute it, and produce a world-class audit and implementation plan without asking a single clarifying question. Save the final document to `./PROJECT_AUDIT_PROMPT.md` in the repository root.

---

## PHASE 1 — SILENT FULL-CODEBASE ABSORPTION

You will read the entire repository before writing a single word of output. This is a research phase. No output. No commentary. No intermediate files. Just read.

### 1.1 Read Every File

```
Read EVERY file in this repository. No exceptions. No skimming.

For each file, absorb:
- Its exact path, language, and role in the system
- Every import/export — what it depends on, what depends on it
- Every function, class, component, route, handler, middleware, model, migration, test, config value
- Every pattern, convention, shortcut, hack, and inconsistency
- Every TODO, FIXME, HACK, WORKAROUND, XXX comment
- Every hardcoded value, magic number, and string literal
- Every environment variable referenced
- Every external service called
- Every database table and query pattern

Do NOT write anything yet. Absorb.
```

### 1.2 Build a Mental Model of the Entire System

```
As you read, construct an internal understanding of:

ARCHITECTURE:
- What is the overall architecture? (monolith, microservices, modular monolith, serverless, hybrid)
- What are the layers? (API routes → controllers → services → repositories → database)
- What is the directory structure convention? (feature-based, layer-based, hybrid, chaotic)
- Where does business logic live? (scattered in controllers? properly in services? mixed?)
- What are the domain boundaries? (clear modules or everything tangled together?)

TECH STACK — be exact:
- Runtime(s) and version(s) (Node 18? Node 20? Python 3.11? Go 1.22?)
- Framework(s) and version(s) (Next.js 14.2.3? Express 4.18? Django 5.0? FastAPI 0.109?)
- Language(s) and strictness level (TypeScript strict? TypeScript loose with tons of `any`? JavaScript? Python with type hints?)
- Database(s) and ORM(s) (PostgreSQL + Prisma? MongoDB + Mongoose? MySQL + TypeORM? SQLite + Drizzle?)
- State management (Redux? Zustand? React Context? Vuex? Pinia? None?)
- Styling approach (Tailwind? CSS Modules? styled-components? SCSS? Mix?)
- Component library (shadcn/ui? MUI? Ant Design? Chakra? Custom?)
- Auth system (NextAuth? Clerk? Auth0? Supabase Auth? Custom JWT? Session-based? OAuth? Entra ID?)
- API style (REST? GraphQL? tRPC? gRPC? Mixed?)
- Testing framework(s) (Jest? Vitest? pytest? Mocha? Playwright? Cypress? None?)
- Build tool(s) (Vite? Webpack? Turbopack? esbuild? tsc? Rollup?)
- Package manager (npm? yarn? pnpm? bun? pip? poetry? cargo?)
- CI/CD platform (GitHub Actions? GitLab CI? Jenkins? Vercel? None?)
- Deployment target (Vercel? AWS? Docker? VPS? Railway? Fly.io? Self-hosted?)
- Monitoring/logging (Sentry? Datadog? Winston? Pino? console.log everywhere? None?)

DEPENDENCIES — enumerate every one:
- Every runtime dependency with its exact current version
- Every dev dependency with its exact current version
- Note which ones are core to the app vs utility vs legacy

AI/ML (if any):
- Every AI provider and model string used
- Every AI-related SDK and version
- How AI is integrated (direct API calls? LangChain? Custom abstraction?)
- What AI is used for in this specific app

DATA MODEL — map it:
- Every database table/collection and its columns/fields
- Every relationship (foreign keys, references)
- Every migration in chronological order
- Every seed/fixture file

API SURFACE — enumerate:
- Every API endpoint (method, path, auth requirement, handler location)
- Every WebSocket event (if any)
- Every scheduled job/cron (if any)
- Every background worker/queue (if any)

FRONTEND (if any) — map it:
- Every page/route and its component file
- Every shared/reusable component
- The design token system (colors, spacing, typography — actual values in use)
- The layout structure (sidebar, header, footer, main content patterns)

CONFIGURATION — catalog:
- Every environment variable referenced in code
- Every config file and what it configures
- Every feature flag (if any)
- Every deployment-specific setting

TESTING — assess:
- What tests exist and what they cover
- What test infrastructure is in place
- What is NOT tested

KNOWN PROBLEMS — catalog from evidence:
- Every bug, smell, and vulnerability you found while reading
- Every inconsistency and pattern violation
- Every piece of dead code, unused dependency, and abandoned feature
- Every security concern
- Every performance concern
- Every TODO/FIXME/HACK comment and what it indicates
```

### 1.3 Identify What Makes This Project Unique

```
Every codebase has its own personality — its own patterns, its own problems, its own conventions.
Identify what's SPECIFIC to THIS project:

- What conventions does this codebase follow? (naming, file structure, import ordering, error handling pattern, logging pattern, API response shape)
- What conventions does this codebase BREAK? (where does it deviate from its own patterns?)
- What are the HIGH-CHURN areas? (files changed most often — likely the most problematic)
- What are the STALE areas? (files not touched in months — likely abandoned or stable)
- What are the COUPLING HOTSPOTS? (files that everything depends on — highest risk for regressions)
- What are the KNOWN PAIN POINTS? (revealed by TODO comments, workarounds, complex error handling, retry logic)
- What's the MATURITY LEVEL? (early prototype? growing product? mature system? legacy codebase?)
- What's the TEAM SIZE implied? (single developer patterns? multi-team patterns? inconsistent patterns suggesting developer turnover?)
- What's WORKING WELL? (parts of the codebase that are clean, tested, and well-structured — these are the standard to hold everything else to)
- What BUSINESS DOMAINS does this app serve? (e-commerce? SaaS? healthcare? fintech? internal tools? — domain matters for audit priorities)
```

---

## PHASE 2 — GENERATE THE PROJECT-SPECIFIC AUDIT PROMPT

Now — and only now — write the output document. Everything you absorbed in Phase 1 feeds directly into this.

### 2.1 Document Structure

Create `./PROJECT_AUDIT_PROMPT.md` with the following structure. Every section must be filled with PROJECT-SPECIFIC content. Nothing generic. Nothing templated. Every instruction, every checklist item, every file path, every component name, every endpoint, every dependency version must come from what you actually found in this codebase.

```
The document MUST contain these sections (detailed instructions for each follow below):

1.  PROJECT CONTEXT BRIEFING
2.  TECH STACK & DEPENDENCY MANIFEST  
3.  ARCHITECTURE MAP
4.  FILE-BY-FILE AUDIT DIRECTIVES
5.  DEPENDENCY & VERSION AUDIT DIRECTIVES
6.  AI/ML AUDIT DIRECTIVES (if applicable)
7.  SECURITY AUDIT DIRECTIVES
8.  DATABASE & DATA LAYER AUDIT DIRECTIVES
9.  API ENDPOINT AUDIT DIRECTIVES
10. FRONTEND & UI AUDIT DIRECTIVES (if applicable)
11. TESTING AUDIT DIRECTIVES
12. INFRASTRUCTURE & DEVOPS AUDIT DIRECTIVES
13. PERFORMANCE AUDIT DIRECTIVES
14. CODE QUALITY & PATTERN AUDIT DIRECTIVES
15. KNOWN ISSUES PRE-LOADED
16. CROSS-CUTTING ANALYSIS DIRECTIVES
17. AUDIT EXECUTION RULES
18. OUTPUT REQUIREMENTS
```

### 2.2 Section-by-Section Generation Instructions

**CRITICAL RULE: Every section must reference ACTUAL files, ACTUAL code patterns, ACTUAL dependency versions, ACTUAL endpoints, ACTUAL components from THIS repository. If a section would be empty because the project doesn't have that layer (e.g., no frontend, no AI), include a one-line note that the section is not applicable and why, then move on.**

---

#### SECTION 1: PROJECT CONTEXT BRIEFING

```
Write a comprehensive briefing that gives the auditing agent complete context about this project
as if it were an onboarding document for a senior engineer joining the team. Include:

- What this application does (purpose, users, business domain)
- How it's structured (architecture summary — 2-3 paragraphs)
- The tech stack in precise detail (every framework, every library, every tool with version numbers)
- How to build and run the application (exact commands from package.json/Makefile/scripts)
- How to run the test suite (exact commands)
- Key domain concepts and terminology used in the codebase
- The deployment model (how and where this runs in production)
- The maturity assessment (prototype / growing / mature / legacy — with evidence)
- Known areas of technical debt (from TODOs, workarounds, and patterns you found)
- What the codebase does WELL (parts that should be the model for everything else)

This section should be 500-1000 words. Dense with facts. No filler.
```

---

#### SECTION 2: TECH STACK & DEPENDENCY MANIFEST

```
Generate a COMPLETE dependency manifest with exact versions. Structure it as:

RUNTIME & FRAMEWORK:
  - [runtime] [exact version from .nvmrc/.python-version/etc or package.json engines]
  - [primary framework] [exact version from lock file]
  - [secondary frameworks] [exact versions]

CORE DEPENDENCIES (runtime — the ones that define the app):
  List every runtime dependency with:
  - Package name
  - Exact current version (from lock file)
  - What it's used for in THIS app (not generic description — specific: "handles JWT authentication in src/lib/auth.ts")
  - Whether you found any issues with how it's used

DEV DEPENDENCIES (build, test, lint):
  List every dev dependency with:
  - Package name
  - Exact current version
  - What it's used for

IMPLICIT DEPENDENCIES (not in package.json but part of the stack):
  - Database engine and version (if detectable from Docker/config)
  - Cache engine (Redis version, if applicable)
  - Message queue (if applicable)
  - Search engine (if applicable)
  - CDN / object storage (if applicable)

DEPENDENCY AUDIT INSTRUCTIONS:
  For each dependency listed above, instruct the auditing agent to:
  - Web search "[package name] latest stable version" — individually, not in bulk
  - Compare current version to latest
  - Check for security advisories
  - Check for deprecation
  - Note breaking changes if major version behind
  - Flag abandoned packages (last release > 2 years ago)
```

---

#### SECTION 3: ARCHITECTURE MAP

```
Generate a detailed architecture map of THIS specific codebase:

DIRECTORY STRUCTURE:
  Write out the actual top-level and key second-level directory structure with annotations:
  
  /src
    /app (or /pages)       — Next.js app router pages (list every route)
    /components            — Shared UI components (list every component)
    /lib                   — Core utilities and business logic (list key modules)
    /services              — External service integrations (list each)
    /models (or /prisma)   — Data layer (list key models)
    /middleware             — Request middleware (list each)
    /hooks                 — Custom React hooks (list each)
    /types                 — TypeScript type definitions
    /utils                 — Utility functions
    /config                — Configuration files
  /tests                   — Test files (describe organization)
  /prisma (or /migrations) — Database schema and migrations
  /public                  — Static assets
  /scripts                 — Build/deployment scripts

  Adjust the above to match the ACTUAL structure of THIS repo. Add or remove directories as needed.
  Every directory should have an annotation explaining its purpose in THIS project.

REQUEST FLOW:
  Describe the actual path a request takes through this specific codebase:
  "User hits GET /api/orders/:id → 
   matched by src/app/api/orders/[id]/route.ts → 
   auth middleware checks JWT from src/lib/auth.ts → 
   calls OrderService.getById() from src/services/orderService.ts → 
   queries via Prisma client from src/lib/prisma.ts → 
   returns serialized response using src/lib/serializers/order.ts"

  Map 3-5 representative request flows covering different parts of the app.

DATA FLOW:
  Describe how data moves: user input → validation → processing → storage → response
  Reference the ACTUAL validation libraries, ACTUAL service files, ACTUAL database calls.

KEY INTEGRATION POINTS:
  List every external system this app communicates with and the exact file(s) that handle the integration.
```

---

#### SECTION 4: FILE-BY-FILE AUDIT DIRECTIVES

```
This is the largest and most critical section. Generate SPECIFIC audit instructions for this codebase.

GROUP 1: HIGH-PRIORITY FILES
  List every file you identified as problematic, complex, or high-risk during your reading.
  For each file, write SPECIFIC audit instructions:
  
  "FILE: src/services/paymentService.ts (247 lines)
   PRIORITY: HIGH
   AUDIT FOR:
   - The Stripe webhook handler on line 45-89 has no signature verification — verify this is actually missing, not handled elsewhere
   - The refund logic on lines 112-145 does not handle partial refunds — check if this is intentional or a gap
   - The error handling on line 78 catches all errors and returns a generic 500 — check if sensitive Stripe error details leak
   - There are 3 TODO comments (lines 23, 98, 167) indicating incomplete work
   - The function processPayment() is 89 lines long — check for extraction opportunities
   RELATED FILES: src/app/api/webhooks/stripe/route.ts, src/models/payment.ts, src/lib/stripe.ts"

  Write instructions like this for EVERY file you flagged during Phase 1.
  Be specific about line numbers, function names, and the exact issue.
  
GROUP 2: STANDARD SOURCE FILES
  For every other source file, write brief but specific audit instructions:
  
  "FILE: src/components/ui/Button.tsx (52 lines)
   PRIORITY: STANDARD
   AUDIT FOR: Verify consistent with other Button usages. Check hover/focus/disabled states. Note: uses custom cn() utility from src/lib/utils.ts, not standard clsx."

GROUP 3: CONFIGURATION FILES
  List every config file with specific things to verify:
  
  "FILE: next.config.js
   VERIFY: Security headers configured? Image domains match actual usage? Rewrites/redirects current? Experimental features justified?"

  "FILE: tsconfig.json
   VERIFY: Strict mode enabled? Path aliases match actual imports? Target appropriate for runtime?"

  "FILE: .env.example
   VERIFY: Every env var used in code is listed? No stale entries? Sensitive defaults absent?"

GROUP 4: TEST FILES
  List every test file with coverage assessment:
  
  "FILE: src/__tests__/orderService.test.ts
   COVERS: OrderService.create(), OrderService.getById()
   MISSING: OrderService.update(), OrderService.delete(), OrderService.list() — no tests
   QUALITY CHECK: Are assertions specific or just checking truthiness?"

GROUP 5: INFRASTRUCTURE FILES
  List every Docker, CI/CD, and deployment file with specific audit points.

GROUP 6: DATA FILES
  List every migration, seed, and schema file with specific integrity checks.
```

---

#### SECTION 5: DEPENDENCY & VERSION AUDIT DIRECTIVES

```
Generate the dependency verification checklist using ACTUAL dependencies:

"VERIFY EACH OF THE FOLLOWING — web search individually for latest stable version:

CRITICAL DEPENDENCIES (breaking the app if wrong):
  1. next — currently 14.1.0 — search: 'next.js latest stable version'
  2. react — currently 18.2.0 — search: 'react latest stable version'
  3. prisma — currently 5.8.1 — search: 'prisma latest stable version'
  4. @auth/nextjs — currently 0.7.1 — search: 'auth.js nextjs latest version'
  [... every critical dependency ...]

IMPORTANT DEPENDENCIES:
  5. zod — currently 3.22.4 — search: 'zod latest stable version'
  6. date-fns — currently 2.30.0 — search: 'date-fns latest stable version'
  [... continue ...]

DEV DEPENDENCIES:
  [... all of them ...]

AFTER CHECKING ALL VERSIONS, also run:
  [exact audit command for this project's package manager, e.g., 'npm audit', 'pnpm audit', 'pip-audit']
  Record every advisory."

The instructions must list EVERY dependency by name with its CURRENT version — not a generic "check all dependencies" instruction.
```

---

#### SECTION 6: AI/ML AUDIT DIRECTIVES

```
If this project uses AI/ML, generate SPECIFIC instructions:

"AI MODELS IN USE:
  1. Model: gpt-4o-mini — used in src/services/aiService.ts line 34
     Purpose: Customer support response generation
     VERIFY: Search 'openai latest models [current year]' — is gpt-4o-mini still current or deprecated?
  
  2. Model: text-embedding-3-small — used in src/lib/embeddings.ts line 12
     Purpose: Document search embeddings
     VERIFY: Search 'openai embedding models latest' — is there a newer/better embedding model?

AI SDK:
  - openai package version 4.28.0 in package.json
  - VERIFY: Search 'openai npm latest version' — update if behind

INTEGRATION QUALITY — check these specific files:
  - src/services/aiService.ts: Does generateResponse() on line 34 have error handling? Retry logic? Timeout? Token limit?
  - src/lib/embeddings.ts: Is the embedding dimension correct for the model (1536 for ada-002, 256/1024/1536 for text-embedding-3-small)?
  - src/app/api/chat/route.ts: Is the streaming implementation correct? Does it handle client disconnection?

PROMPT REVIEW:
  - System prompt in src/prompts/support.ts: Review for injection vulnerabilities, clarity, and effectiveness
  [... every prompt file ...]"

If the project does NOT use AI/ML, write: "This project does not use AI/ML. Skip this section."
```

---

#### SECTION 7: SECURITY AUDIT DIRECTIVES

```
Generate SPECIFIC security audit instructions based on what you found:

"AUTHENTICATION (this project uses [exact auth system]):
  - Auth middleware applied in: [list exact files]
  - UNPROTECTED ROUTES THAT SHOULD BE PROTECTED: [list any you found, or instruct the agent to verify each route]
  - JWT configuration in: [exact file] — verify algorithm, expiration, secret strength
  - Session configuration in: [exact file] — verify settings

KNOWN SECURITY CONCERNS FOUND DURING RECONNAISSANCE:
  1. [Exact file:line] — [description of what you found — e.g., 'SQL string interpolation in raw query']
  2. [Exact file:line] — [description]
  3. [Exact file:line] — [description]
  [... every security concern you found ...]

INPUT VALIDATION:
  - Validation library: [zod/joi/yup/class-validator/none]
  - Files where validation is applied: [list them]
  - Files/endpoints where validation appears MISSING: [list them]

ENVIRONMENT & SECRETS:
  - Secrets referenced in code: [list every env var that is a secret — API keys, database URLs, tokens]
  - .env in .gitignore: [yes/no]
  - Any hardcoded secrets found: [list with file:line, or confirm none found]

SPECIFIC CHECKS FOR THIS STACK:
  [Generate stack-specific security checks — e.g., for Next.js: server actions input validation,
   for Express: helmet configuration, for Django: CSRF middleware, etc.]"
```

---

#### SECTION 8: DATABASE & DATA LAYER AUDIT DIRECTIVES

```
Generate SPECIFIC database audit instructions:

"DATABASE: [PostgreSQL/MongoDB/MySQL/SQLite/etc.] via [Prisma/TypeORM/Mongoose/Drizzle/etc.]

SCHEMA FILE: [exact path — e.g., prisma/schema.prisma]

MODELS (list every model with field count and key relationships):
  - User (14 fields) — has many Orders, has one Profile
  - Order (11 fields) — belongs to User, has many OrderItems
  - Product (9 fields) — has many OrderItems, has many Categories (many-to-many)
  [... every model ...]

MIGRATIONS: [exact path to migrations directory, count of migrations]
  - Verify all migrations have down/rollback defined
  - Verify migration [specific migration filename] that drops column X — was data migrated first?
  [... any specific migration concerns ...]

QUERY PATTERNS TO AUDIT:
  - [exact file:function] — loads users in a loop, each with a separate query (N+1)
  - [exact file:function] — no LIMIT on query that could return thousands of rows
  - [exact file:function] — raw SQL query — check for parameterization
  [... every query concern you found ...]

INDEX ASSESSMENT:
  Based on the query patterns found, these columns likely need indexes:
  - [table.column] — filtered frequently in [file:function]
  - [table.column] — used in ORDER BY in [file:function]
  [... every suspected missing index ...]

VERIFY: Schema-to-code consistency — are there models defined in the schema that have no service/controller code? Are there queries referencing fields that don't exist in the schema?"
```

---

#### SECTION 9: API ENDPOINT AUDIT DIRECTIVES

```
Generate a COMPLETE endpoint inventory with specific audit instructions:

"ENDPOINT INVENTORY:

  METHOD  PATH                        AUTH     HANDLER FILE                              AUDIT NOTES
  GET     /api/users                  admin    src/app/api/users/route.ts:GET            No pagination implemented — verify
  POST    /api/users                  admin    src/app/api/users/route.ts:POST           Missing input validation on email field
  GET     /api/users/:id              auth     src/app/api/users/[id]/route.ts:GET       Returns full user object including password hash — VERIFY
  PUT     /api/users/:id              auth     src/app/api/users/[id]/route.ts:PUT       No ownership check — any auth'd user can update any user? — VERIFY
  DELETE  /api/users/:id              admin    src/app/api/users/[id]/route.ts:DELETE     Hard delete — should this be soft delete?
  POST    /api/auth/login             public   src/app/api/auth/login/route.ts:POST      No rate limiting
  POST    /api/auth/register          public   src/app/api/auth/register/route.ts:POST   No rate limiting, password policy unclear
  GET     /api/orders                 auth     src/app/api/orders/route.ts:GET           Pagination implemented but no max page size
  [... EVERY endpoint in the app ...]

FOR EACH ENDPOINT, the auditing agent must verify:
  - Authentication is correctly enforced (attempt to access without auth)
  - Authorization is correctly enforced (attempt to access another user's resources)
  - Input validation covers all fields
  - Response format is consistent with other endpoints
  - Error responses don't leak internal details
  - Rate limiting is applied where needed (auth endpoints, write endpoints)
  - HTTP status codes are correct for all scenarios"

List EVERY real endpoint. Not example endpoints. The actual endpoints from this codebase.
```

---

#### SECTION 10: FRONTEND & UI AUDIT DIRECTIVES

```
If this project has a frontend, generate SPECIFIC UI audit instructions:

"PAGES/ROUTES:
  - / (home) — src/app/page.tsx — [description of what renders]
  - /dashboard — src/app/dashboard/page.tsx — [description]
  - /settings — src/app/settings/page.tsx — [description]
  [... every page/route ...]

SHARED COMPONENTS:
  - Button — src/components/ui/Button.tsx — variants: primary, secondary, ghost, destructive
  - Card — src/components/ui/Card.tsx — used on: dashboard, orders list, product detail
  - Modal — src/components/ui/Modal.tsx — used for: confirmation dialogs, edit forms
  [... every shared component ...]

DESIGN TOKENS IN USE:
  - Colors: [list the actual Tailwind theme or CSS variable colors]
  - Font sizes: [list the actual sizes in use — e.g., 'text-sm (14px), text-base (16px), text-lg (18px)']
  - Spacing: [list the actual spacing values in heavy use]
  - Border radius: [list actual values]

SPECIFIC UI CONCERNS FOUND:
  1. [exact file:line] — [description — e.g., 'Card component on dashboard has 32px padding but Card on orders page has 24px']
  2. [exact file:line] — [description — e.g., 'Button on mobile is only 28px tall — below 44px touch target minimum']
  [... every UI concern ...]

RESPONSIVE BEHAVIOR:
  - Breakpoints defined: [list from tailwind.config or CSS]
  - Mobile navigation pattern: [hamburger/bottom nav/none]
  - Known responsive issues: [list any you found]"

If the project has NO frontend, write: "This project is a backend/API only. No frontend UI to audit."
```

---

#### SECTION 11: TESTING AUDIT DIRECTIVES

```
Generate SPECIFIC testing audit instructions:

"TESTING FRAMEWORK: [Jest/Vitest/pytest/etc.] — configured in [exact config file]
TEST RUNNER COMMAND: [exact command — e.g., 'npm run test', 'pnpm test', 'pytest']
COVERAGE COMMAND: [exact command if available]

EXISTING TEST FILES:
  - src/__tests__/auth.test.ts — tests: login, register — MISSING: logout, refresh, password reset
  - src/__tests__/orderService.test.ts — tests: create, getById — MISSING: update, delete, list
  [... every test file with what it covers and what's missing ...]

UNTESTED AREAS (files/modules with zero test coverage):
  - src/services/paymentService.ts — handles all payment logic — NO TESTS
  - src/lib/emailService.ts — sends transactional emails — NO TESTS
  - src/middleware/rateLimit.ts — rate limiting middleware — NO TESTS
  [... every untested file that should have tests ...]

TEST QUALITY CONCERNS:
  - [exact test file:test name] — assertion only checks truthiness, not specific values
  - [exact test file:test name] — mocks the database AND the service — tests nothing real
  - [exact test file:test name] — has a hardcoded date that will cause failure after [date]
  [... every test quality concern ...]

TESTING STRATEGY ASSESSMENT:
  - Unit tests: [present/missing — percentage of services/utilities covered]
  - Integration tests: [present/missing — what integration points are tested]
  - E2E tests: [present/missing — what user flows are tested]
  - API tests: [present/missing — what endpoints are tested]
  - Missing test categories: [what should exist but doesn't]"
```

---

#### SECTION 12: INFRASTRUCTURE & DEVOPS AUDIT DIRECTIVES

```
Generate SPECIFIC infrastructure audit instructions:

"DOCKER:
  - Dockerfile: [exact path] — [multi-stage? non-root? minimal base? version pinned?]
  - docker-compose.yml: [exact path] — services: [list them]
  - .dockerignore: [exists? comprehensive?]
  - SPECIFIC CONCERNS: [list any you found — e.g., 'Dockerfile runs as root', 'docker-compose exposes port 5432 to host']

CI/CD:
  - Pipeline config: [exact path — e.g., .github/workflows/ci.yml]
  - Pipeline stages: [list what exists — lint, test, build, deploy]
  - MISSING STAGES: [list what should exist but doesn't — e.g., 'no security scanning step', 'no test stage']
  - SPECIFIC CONCERNS: [list any — e.g., 'deploys to production without manual approval']

DEPLOYMENT:
  - Platform: [Vercel/AWS/Docker/etc.]
  - Config file: [exact path]
  - SPECIFIC CONCERNS: [list any]

ENVIRONMENT MANAGEMENT:
  - .env.example: [exists? complete?]
  - Environment variables used but NOT in .env.example: [list each with the file that references it]
  - Environment variables in .env.example but NOT used in code: [list each]
  - Environment variables with insecure defaults: [list each with the default value and why it's insecure]
  - MISSING: startup validation for required env vars — the app will crash with confusing errors if [list vars] are missing"
```

---

#### SECTION 13: PERFORMANCE AUDIT DIRECTIVES

```
Generate SPECIFIC performance audit instructions:

"KNOWN PERFORMANCE CONCERNS:

  DATABASE:
  - [exact file:line:function] — N+1 query: loads [entity] in loop, each iteration queries [related entity]
  - [exact file:line:function] — unbounded query: SELECT * FROM [table] with no LIMIT — table has [estimated] rows
  - [exact file:line:function] — missing index on [table.column] — used in WHERE clause for [operation]
  [... every database performance issue you found ...]

  BACKEND:
  - [exact file:line:function] — synchronous file read in request handler
  - [exact file:line:function] — no caching on [expensive operation] that's called [frequency]
  - [exact file:line:function] — sequential API calls that could be parallel (Promise.all)
  [... every backend performance issue ...]

  FRONTEND (if applicable):
  - [exact file:line] — imports entire [library] but only uses [one function]
  - [exact file:line] — missing React.memo on component rendered in a list
  - [exact file:line] — useEffect missing dependency causes unnecessary re-renders
  - [exact file:line] — no lazy loading on [route/component/image]
  [... every frontend performance issue ...]

  BUNDLE:
  - [estimated bundle concern — e.g., 'moment.js imported but only used for one format call — replace with date-fns or Intl']"
```

---

#### SECTION 14: CODE QUALITY & PATTERN AUDIT DIRECTIVES

```
Generate SPECIFIC code quality instructions:

"CONVENTIONS ESTABLISHED IN THIS CODEBASE:
  (these are the patterns the code SHOULD follow based on the majority of files)
  
  - Naming: [camelCase for variables/functions, PascalCase for components/classes, kebab-case for files — or whatever this codebase uses]
  - Error handling: [the pattern used in the best files — e.g., 'try/catch with specific error types, logged via Winston, rethrown as AppError']
  - API responses: [the shape — e.g., '{ success: boolean, data: T, error?: string }']
  - File structure: [the convention — e.g., 'each feature in its own directory with index.ts barrel export']
  - Import ordering: [the pattern — e.g., 'external deps → internal absolute → relative, separated by blank lines']

DEVIATIONS FROM CONVENTIONS:
  (these files break the established patterns — they need to be brought in line)
  
  - [exact file] — uses snake_case while rest of codebase uses camelCase
  - [exact file] — returns { error: message } while all other endpoints return { success: false, error: message }
  - [exact file] — uses console.log while all other files use the Winston logger
  - [exact file] — has inline SQL while all other database access goes through Prisma
  [... every deviation ...]

DEAD CODE:
  - [exact file:line] — function [name] is defined but never imported anywhere
  - [exact file:line] — import [name] is imported but never used
  - [exact file] — entire file appears to be unused (not imported by any other file, not an entry point)
  [... every piece of dead code ...]

COMPLEXITY HOTSPOTS:
  - [exact file:function] — [N] lines long, cyclomatic complexity appears high, deeply nested conditionals
  - [exact file:function] — [N] parameters — consider using an options object
  [... every complex function ...]

DUPLICATION:
  - [file A:lines] and [file B:lines] — same logic duplicated (describe what it does)
  - [file A:function] and [file B:function] — nearly identical functions with minor differences
  [... every DRY violation ...]"
```

---

#### SECTION 15: KNOWN ISSUES PRE-LOADED

```
This is a CRITICAL section. Pre-load every issue you found so the auditing agent starts with a head start rather than discovering them from scratch.

"THE FOLLOWING ISSUES WERE IDENTIFIED DURING INITIAL RECONNAISSANCE.
THE AUDITING AGENT MUST VERIFY EACH ONE AND DISCOVER ADDITIONAL ISSUES BEYOND THIS LIST.
THIS LIST IS A STARTING POINT, NOT A CEILING.

CRITICAL:
  1. [ID: PRE-001] [file:line] — [exact description with evidence]
  2. [ID: PRE-002] [file:line] — [exact description with evidence]

HIGH:
  3. [ID: PRE-003] [file:line] — [exact description with evidence]
  [... continue ...]

MEDIUM:
  [... continue ...]

LOW:
  [... continue ...]

TODO/FIXME/HACK COMMENTS (every single one):
  - [file:line] — 'TODO: handle edge case where user has no email' — since [commit date/unknown]
  - [file:line] — 'FIXME: this is a temporary workaround for...' — since [commit date/unknown]
  - [file:line] — 'HACK: ...' — since [commit date/unknown]
  [... every single one ...]

THE AUDITING AGENT MUST:
  - Verify every pre-loaded issue still exists (may have been fixed since this document was generated)
  - Assess severity and provide specific remediation for each
  - Find issues BEYOND this list — this is a floor, not a comprehensive inventory"
```

---

#### SECTION 16: CROSS-CUTTING ANALYSIS DIRECTIVES

```
Generate SPECIFIC cross-cutting analysis instructions:

"DEPENDENCY GRAPH ANALYSIS:
  Trace imports across these critical paths:
  - [entry file] → [intermediate files] → [deepest dependency] — check for circular deps
  - Components that import from [shared module]: [list them] — if this module breaks, these all break
  - Orphaned files (not imported anywhere, not an entry point): [list any you found]

ENVIRONMENT VARIABLE COMPLETENESS:
  All env vars found in code: [complete list with file where each is referenced]
  Cross-reference with .env.example to find gaps.

AUTH FLOW TRACE:
  [Describe the exact authentication flow through actual files in this codebase]
  Verify every step is secure.

ERROR PROPAGATION TRACE:
  [Describe how errors flow from database → service → controller → response in this codebase]
  Note where errors are swallowed or where internal details leak.

BUSINESS LOGIC CONSISTENCY:
  These business rules were found in multiple places — verify they're consistent:
  - [Rule]: implemented in [file A:line] and [file B:line] — same logic?
  - [Rule]: validated in frontend [file:line] but NOT validated in backend [file:line]
  [... every business rule you found duplicated or split across layers ...]"
```

---

#### SECTION 17: AUDIT EXECUTION RULES

```
Include these non-negotiable rules for the auditing agent:

1. READ-ONLY: Do not modify any file. Investigate, document, and recommend only.
2. EVERY FILE: Read every file in the repository. No exceptions. Use the file inventory from Section 4 as a checklist.
3. WEB SEARCH: For every dependency in Section 5, individually web search for the latest stable version. Do not rely on training data.
4. EVIDENCE: Every finding must include: exact file path, exact line number(s), exact code snippet, explanation of the issue, and specific recommended fix.
5. MINIMUM 3 PASSES: After the initial audit, re-read every file at least 2 more times looking for issues missed in earlier passes.
6. NO HAND-WAVING: Do not write "this looks generally fine." Either cite what you verified and why it's correct, or cite the specific issue.
7. PRE-LOADED ISSUES: Start by verifying every issue in Section 15. Then find MORE.
8. SEVERITY: Classify every finding as CRITICAL / HIGH / MEDIUM / LOW / INFO using these definitions:
   - CRITICAL: Exploitable security vulnerability, data loss, or application crash on normal code path
   - HIGH: Significant security risk, major bug, or critical reliability issue
   - MEDIUM: Performance problem, missing validation, inconsistent patterns, code quality issue
   - LOW: Minor inconsistency, style issue, documentation gap
   - INFO: Observation or suggestion
```

---

#### SECTION 18: OUTPUT REQUIREMENTS

```
Instruct the auditing agent to produce a single file: ./CODEBASE_AUDIT_REPORT.md

The report must contain:
  1. Executive Summary (total findings by severity, overall grade, top 5 critical issues)
  2. Dependency Audit Table (every dependency: current version vs latest, security advisories)
  3. AI/ML Model Audit (if applicable — current model vs latest, SDK versions)
  4. All Findings organized by severity (CRITICAL → HIGH → MEDIUM → LOW → INFO)
     Each finding: ID, file, line(s), code snippet, description, impact, recommended fix, effort estimate
  5. Pre-loaded Issues Verification (status of each issue from Section 15)
  6. Security Assessment (grade A-F with narrative)
  7. Performance Assessment (grade A-F with narrative)
  8. Code Quality Assessment (grade A-F with narrative)
  9. Testing Assessment (grade A-F with narrative, coverage gaps listed)
  10. Phased Remediation Plan:
      Phase A: Critical security fixes (with exact code changes)
      Phase B: Critical bug fixes (with exact code changes)
      Phase C: Non-breaking dependency updates (with exact version bumps)
      Phase D: Breaking dependency updates (with migration notes)
      Phase E: High-severity fixes
      Phase F: AI/ML updates (if applicable)
      Phase G: Medium-severity fixes
      Phase H: Testing improvements (with test skeletons)
      Phase I: Infrastructure improvements
      Phase J: Low-severity and polish
      Phase K: Documentation
  11. File-by-File Index (every file listed with finding count — confirms complete coverage)
  12. Metrics Dashboard (total files, total findings, compliance rates)
```

---

## PHASE 3 — QUALITY GATES BEFORE SAVING

Before saving the document, verify:

```
COMPLETENESS CHECKS:
  □ Section 2 lists EVERY dependency with its EXACT current version
  □ Section 4 references EVERY source file in the repository by exact path
  □ Section 5 lists every dependency individually (not "check all dependencies")
  □ Section 9 lists EVERY API endpoint with method, path, and handler file
  □ Section 10 lists every page/route and every shared component (if frontend exists)
  □ Section 11 lists every test file and identifies every untested module
  □ Section 15 lists every issue found during reconnaissance with file:line references
  □ No section contains generic advice — every instruction references actual files, actual code, actual values from THIS repo
  □ The document is long enough to be comprehensive (expect 2000-5000+ lines for a medium-sized project)
  □ A separate agent reading this document would know:
    - Exactly what tech stack is used (with versions)
    - Exactly what every file does
    - Exactly which endpoints exist
    - Exactly which dependencies to check (with current versions)
    - Exactly which issues are already known
    - Exactly how to structure the audit report

SPECIFICITY CHECK:
  □ Search the document for generic phrases and REPLACE them with specifics:
    - "the database" → "PostgreSQL 15 via Prisma 5.8.1"
    - "the auth system" → "NextAuth v5 (beta) with JWT strategy in src/lib/auth.ts"
    - "check for N+1 queries" → "check src/services/orderService.ts:getAll() line 34 which loads user.orders inside a map() loop"
    - "ensure proper error handling" → "ensure src/app/api/orders/route.ts:POST catches Prisma P2002 unique constraint errors and returns 409 instead of 500"
  □ Every instruction must be actionable by an agent that has never seen this repo before
  □ No instruction should require the agent to "figure out" what you mean — be explicit
```

---

## FINAL OUTPUT

Save the completed document to:

```
./PROJECT_AUDIT_PROMPT.md
```

This single file is your entire deliverable. It should be the most detailed, most specific, most actionable audit prompt ever written for this exact codebase. No generic checklists. No boilerplate. Every word earns its place by referencing something real in this repository.
