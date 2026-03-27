# MARKAI Master Implementation Plan

> **Generated:** 2026-03-26 | **Audited by:** Claude Opus 4.6 | **Status:** Pending Approval

This document consolidates the findings from a comprehensive audit of every file in the MARKAI codebase across 4 domains (frontend, backend, agents/workflows, infrastructure) and includes benchmark content outputs for the Healthspan brand. It is organized into prioritized phases for implementation.

---

## Table of Contents

1. [Audit Summary](#1-audit-summary)
2. [Phase 1: Critical Production Blockers](#2-phase-1-critical-production-blockers)
3. [Phase 2: Data Flow & Workflow Fixes](#3-phase-2-data-flow--workflow-fixes)
4. [Phase 3: Security Hardening](#4-phase-3-security-hardening)
5. [Phase 4: Frontend Polish & UX](#5-phase-4-frontend-polish--ux)
6. [Phase 5: Infrastructure & Observability](#6-phase-5-infrastructure--observability)
7. [Phase 6: Pipeline Completeness](#7-phase-6-pipeline-completeness)
8. [Benchmark Content Review](#8-benchmark-content-review)
9. [Files Changed Summary](#9-files-changed-summary)

---

## 1. Audit Summary

| Domain | Files Audited | Critical | High | Medium | Low |
|--------|:---:|:---:|:---:|:---:|:---:|
| **Frontend** | 67 | 0 | 5 | 12 | 8 |
| **Backend** | ~40 | 5 | 6 | 5 | 5 |
| **Agents/Workflows** | 45 | 3 | 3 | 3 | — |
| **Infrastructure** | 18 | 6 | 8 | 6 | — |
| **TOTAL** | **~170** | **14** | **22** | **26** | **13** |

**Overall Grade: B-** — Solid architecture and excellent localization, but 14 critical issues must be resolved before any production deployment.

---

## 2. Phase 1: Critical Production Blockers

> **Priority:** MUST FIX before any testing or deployment
> **Estimated items:** 14

### P1-01: LiteLLM Invalid Model Names
- **File:** `litellm/config.yaml`
- **Issue:** `gpt-4.1-mini` and `gpt-4.1` are not valid OpenAI model IDs. All LLM calls using these models will fail.
- **Fix:** Replace with valid model names (`gpt-4-turbo`, `gpt-4o`, or keep `gpt-4o-mini`). Add fallback model configuration.

### P1-02: MinIO Endpoint Wrong Port
- **File:** `.env` (line: `MINIO_ENDPOINT=minio:9001`)
- **Issue:** Port 9001 is the MinIO Console (web UI), not the S3-compatible API. All file upload/download operations fail silently.
- **Fix:** Change to `MINIO_ENDPOINT=minio:9000`

### P1-03: Traefik Using Let's Encrypt STAGING
- **File:** `traefik/traefik.yml`
- **Issue:** `caServer: https://acme-staging-v02.api.letsencrypt.org/directory` generates untrusted certificates. Browsers will show SSL warnings.
- **Fix:** Change to `https://acme-v02.api.letsencrypt.org/directory` and update email from placeholder.

### P1-04: Traefik Dashboard Unsecured
- **File:** `traefik/traefik.yml`
- **Issue:** `insecure: true` exposes the full Traefik API and routing configuration without authentication.
- **Fix:** Either disable the dashboard or add basicAuth middleware.

### P1-05: Calendar Items Field Mapping Mismatch
- **File:** `agents/workflows/planning/nodes.py` (lines 112-122)
- **Issue:** LLM outputs fields `campaign_name, scheduled_date, platform, content_type, theme, product_name, brief` but `store_calendar_items()` expects `title, description, channel, scheduled_at`. Calendar items are stored with wrong/missing data.
- **Fix:** Add field mapping layer: `title=theme`, `description=brief`, `channel=platform`, `scheduled_at=scheduled_date`.

### P1-06: Strategy/Planning Load Wrong Data Field
- **File:** `agents/workflows/strategy/nodes.py` (line 24), `agents/workflows/planning/nodes.py` (line 26)
- **Issue:** Code reads `research.get("data", research)` but agent_runs store results in `output_payload`, not `data`. Strategy and planning workflows operate on wrong/empty data.
- **Fix:** Change to `.get("output_payload", research)` in both files.

### P1-07: Content Workflow Missing supplier_website
- **File:** `agents/workflows/content/nodes.py` (lines 45 vs 133)
- **Issue:** DB query selects `id, brand_guidelines, tone_of_voice, target_audience` but line 133 reads `config.get("supplier_website")`. Always None — product image sourcing from supplier sites never works.
- **Fix:** Add `website_url` to the SELECT query, or load supplier URLs from products table.

### P1-08: Research Stored in Wrong Payload Field
- **File:** `agents/shared/tools/database.py` (lines 108-115)
- **Issue:** `store_research()` writes to `input_payload` instead of `output_payload`. Downstream workflows loading research via `output_payload` get nothing.
- **Fix:** Change to `output_payload` in the INSERT statement.

### P1-09: FRONTEND_URL Missing from .env
- **File:** `.env`
- **Issue:** `FRONTEND_URL` not set, causing CORS to use wildcard `["*"]`. Security risk and may break credentialed requests.
- **Fix:** Add `FRONTEND_URL=http://localhost:3000` (dev) or the production domain.

### P1-10: Missing Health Checks on 12 Services
- **File:** `docker-compose.yml`
- **Issue:** Only PostgreSQL has a health check. All other services (qdrant, minio, valkey, nats, litellm, backend, frontend, agents, browser-worker, notifications, traefik, n8n) have none.
- **Fix:** Add health checks for at minimum: backend, nats, minio, litellm, valkey.

### P1-11: Webhook Secret Timing Attack
- **File:** `backend/app/api/v1/webhooks.py` (line 26)
- **Issue:** Uses `!=` string comparison for secret verification. Vulnerable to timing attacks.
- **Fix:** Replace with `secrets.compare_digest(incoming_secret, configured_secret)`

### P1-12: Fabric Service BC Image Lookup Not Implemented
- **File:** `agents/shared/tools/fabric.py` (lines 89-97)
- **Issue:** `get_product_image_from_bc()` always returns `None`. Product images never sourced from Business Central.
- **Fix:** Implement actual BC image query or remove the function and rely on supplier/web image sourcing.

### P1-13: Chain Failure Silently Swallowed
- **File:** `agents/worker.py` (lines 160-161)
- **Issue:** If NATS publish fails when chaining (e.g., research → strategy), error is logged but original message is ACKed. Pipeline stops silently.
- **Fix:** If chain publish fails, NAK the message with delay to retry the chain, or create an alert/notification.

### P1-14: Hardcoded Default Secrets in Config
- **File:** `backend/app/config.py`
- **Issue:** `SECRET_KEY = "change-me-to-a-random-string"`, `POSTGRES_PASSWORD = "change-me"`, `MINIO_SECRET_KEY = "change-me"`. If env vars aren't set, these defaults are used.
- **Fix:** Add startup validation that raises an error if critical secrets are still default values in production.

---

## 3. Phase 2: Data Flow & Workflow Fixes

> **Priority:** HIGH — Required for correct pipeline execution
> **Estimated items:** 12

### P2-01: N+1 Query in Intelligence Reports
- **File:** `backend/app/api/v1/intelligence.py` (lines 225-232)
- **Issue:** Competitors fetched in loop without eager loading.
- **Fix:** Use JOIN or `selectinload()` to batch-load relationships.

### P2-02: Missing Transaction Rollback
- **File:** `backend/app/api/v1/brands.py` (lines 94-102)
- **Issue:** If `db.execute()` or `db.commit()` fails mid-operation, no rollback leaves inconsistent state.
- **Fix:** Wrap in explicit `async with db.begin():` block.

### P2-03: JSONB Mutation Inconsistency
- **File:** `backend/app/services/brand_service.py`
- **Issue:** Some code paths use `flag_modified()` for JSONB columns, others don't. Mutations may not persist.
- **Fix:** Audit all JSONB writes and ensure `flag_modified()` is called consistently.

### P2-04: Product Sync Race Condition
- **File:** `backend/app/scheduler/bc_sync.py` (lines 95-100)
- **Issue:** Concurrent syncs could upsert same product. `expiry_date_map.setdefault()` creates incomplete data.
- **Fix:** Add database-level unique constraint and use advisory locks during sync.

### P2-05: Token Caching Without Thread Safety
- **File:** `backend/app/auth/entra.py` (lines 71-107)
- **Issue:** Global token cache accessed by multiple concurrent requests without locking.
- **Fix:** Use `asyncio.Lock()` to serialize token refresh operations.

### P2-06: Missing NULL Checks in Analytics
- **File:** `backend/app/api/v1/analytics.py` (line 39)
- **Issue:** `round(float(row[5]), 4)` fails if engagement_rate is None.
- **Fix:** Add `if row[5] is not None` guard.

### P2-07: Unsafe File Extension Extraction
- **File:** `backend/app/api/v1/brands.py` (line 188)
- **Issue:** `file.filename.rsplit(".", 1)[-1]` fails for files with no extension.
- **Fix:** Add: `ext = file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "bin"`

### P2-08: Calendar Table Missing product_id Storage
- **File:** `agents/shared/tools/database.py` + `agents/workflows/planning/nodes.py` (line 119)
- **Issue:** Planning tries to store product_id on calendar items, but database insert doesn't include it.
- **Fix:** Add product_ids column to calendar_items INSERT in database.py.

### P2-09: Content is_current Always True
- **File:** `agents/shared/tools/database.py` (content storage)
- **Issue:** `is_current=true` set for every new content version. Multiple versions all marked current.
- **Fix:** Set previous versions to `is_current=false` before inserting new one.

### P2-10: JSON Parsing Without Error Handling
- **File:** `backend/app/api/v1/intelligence.py` (lines 493-501)
- **Issue:** `json.loads(content)` can throw JSONDecodeError but not caught.
- **Fix:** Wrap in try/except with meaningful error response.

### P2-11: Missing Pagination Headers
- **File:** `backend/app/api/v1/approvals.py` (lines 16-31)
- **Issue:** Uses skip/limit but response has no total count. Frontend can't paginate.
- **Fix:** Add `X-Total-Count` header or return `{ items: [], total: N }`.

### P2-12: Fabric Connection NULL Check
- **File:** `backend/app/services/fabric_service.py` (lines 80-89)
- **Issue:** `conn.close()` in finally but connection might be None.
- **Fix:** Add `if conn:` guard.

---

## 4. Phase 3: Security Hardening

> **Priority:** HIGH — Must address before production
> **Estimated items:** 8

### P3-01: SQL Injection Risk in Fabric Service
- **File:** `backend/app/services/fabric_service.py` (lines 94-96)
- **Issue:** `_safe_table_name()` validates via regex but `settings.BC_TABLE_ITEMS` is configurable.
- **Fix:** Add a whitelist of allowed table names.

### P3-02: OData Filter Injection
- **File:** `backend/app/auth/entra.py` (line 118)
- **Issue:** Query escaping only replaces single quotes. Incomplete for OData injection prevention.
- **Fix:** Use proper OData escaping or parameterized Graph API queries.

### P3-03: Prompt Injection Risk in Agent Prompts
- **File:** All `agents/workflows/*/nodes.py`
- **Issue:** User-supplied brand data (guidelines, descriptions) passed directly into LLM prompts without sanitization.
- **Fix:** Sanitize inputs: strip control characters, limit length, escape special tokens.

### P3-04: Credentials in Exception Logs
- **File:** `backend/app/main.py` (line 85)
- **Issue:** `traceback.format_exc()` could expose secrets in error logs.
- **Fix:** Sanitize exception details before logging. Strip known env var patterns.

### P3-05: Secrets in Repository .env
- **File:** `.env`, `frontend/.env.local`
- **Issue:** Real API keys, client secrets, and tokens committed to repo.
- **Fix:** Move to secrets management (Vault, Azure Key Vault). Add `.env` to `.gitignore`. Use `.env.example` with placeholder values only.

### P3-06: Missing CSRF Protection
- **File:** `backend/app/api/router.py`
- **Issue:** No CSRF tokens on state-changing endpoints.
- **Fix:** Since the app uses Bearer token auth (not cookies), CSRF is mitigated. Document this explicitly. If cookies are ever used, add CSRF middleware.

### P3-07: Grafana Default Credentials
- **File:** `observability/grafana/grafana.ini`
- **Issue:** `admin_user = admin`, `admin_password = admin`.
- **Fix:** Change to strong credentials or integrate with Azure AD SSO.

### P3-08: Loki Auth Disabled
- **File:** `observability/loki/loki-config.yaml`
- **Issue:** `auth_enabled: false` — anyone on the network can query logs.
- **Fix:** Enable auth or restrict network access to internal only.

---

## 5. Phase 4: Frontend Polish & UX

> **Priority:** MEDIUM — Improves user experience
> **Estimated items:** 15

### P4-01: Kanban Board Not Responsive
- **File:** `frontend/src/components/content/KanbanBoard.tsx` (line 154)
- **Issue:** Fixed `grid-cols-4` breaks on mobile/tablet.
- **Fix:** Change to `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`.

### P4-02: Silent Error Catches Need Toast Notifications
- **Files:** `frontend/src/app/content/page.tsx` (line 61-62), `frontend/src/components/layout/BrandSwitcher.tsx` (line 25-26), `frontend/src/components/layout/Header.tsx` (line 34-42)
- **Issue:** API failures silently set empty state. User doesn't know data failed to load.
- **Fix:** Add `toast.error("Failed to load X")` in all catch blocks.

### P4-03: Brand Switching Race Condition
- **File:** `frontend/src/app/content/page.tsx` (lines 54-79)
- **Issue:** Rapid brand switching causes multiple pending API requests to race.
- **Fix:** Add `AbortController` to cancel previous request when new one starts.

### P4-04: Calendar Cell Overflow on Mobile
- **File:** `frontend/src/components/content/CalendarView.tsx` (lines 125-127)
- **Issue:** `min-h-[110px]` clips content on small screens.
- **Fix:** Add `min-h-[80px] sm:min-h-[110px]` and `overflow-y-auto` on cell content.

### P4-05: Missing Accessibility Labels
- **Files:** Header.tsx (avatar alt, notification badge aria-label), Sidebar.tsx, multiple dialogs
- **Issue:** Icon-only buttons and badges missing `aria-label` for screen readers.
- **Fix:** Add `aria-label` to all icon buttons and status badges.

### P4-06: Unused Components
- **Files:** `BrandOnboarding.tsx`, `CompetitorTracker.tsx`
- **Issue:** Components exist but are not imported in any page.
- **Fix:** Either wire them into the brand detail page or remove them.

### P4-07: Approval List Doesn't Refresh After Action
- **File:** `frontend/src/app/approvals/page.tsx` (lines 33-42)
- **Issue:** After approve/reject, item removed from list but page doesn't refetch. Dashboard stats may be stale.
- **Fix:** Call `fetchApprovals()` after successful action.

### P4-08: URL Validation on Brand Form
- **File:** `frontend/src/components/brand/BrandForm.tsx`
- **Issue:** Website URLs not validated before submission. Invalid URLs could break browser-worker.
- **Fix:** Add `try { new URL(value) } catch { toast.error("Invalid URL") }` validation.

### P4-09: Error States Missing Retry Button
- **File:** `frontend/src/app/brands/page.tsx` (line 22)
- **Issue:** Error state shows message but no recovery action.
- **Fix:** Add "Retry" button that calls `fetchBrands()`.

### P4-10: Settings Timezone Select Not Responsive
- **File:** `frontend/src/app/settings/page.tsx` (lines 185-206)
- **Issue:** `<select>` elements may overflow on mobile.
- **Fix:** Add `w-full md:max-w-[250px]`.

### P4-11: Header Breadcrumbs May Wrap Awkwardly
- **File:** `frontend/src/components/layout/Header.tsx` (lines 65-81)
- **Issue:** Long brand names cause breadcrumb text to clip.
- **Fix:** Add `truncate max-w-[200px]` on breadcrumb labels.

### P4-12: ApprovalActions Buttons Don't Wrap on Mobile
- **File:** `frontend/src/components/approval/ApprovalActions.tsx` (lines 40-54)
- **Fix:** Change to `flex-col sm:flex-row`.

### P4-13: Brands Detail Page Too Large — Needs Splitting
- **File:** `frontend/src/app/brands/[id]/page.tsx` (~20,700 tokens)
- **Issue:** Single file handles Overview, Channels, Logos, Intelligence, Products, Edit, Competitors, Performance tabs.
- **Fix:** Extract each tab into its own component file under `components/brand/tabs/`.

### P4-14: Calendar View Needs Virtualization
- **File:** `frontend/src/components/content/CalendarView.tsx`
- **Issue:** No pagination — renders entire month of items. 1000+ items would be slow.
- **Fix:** Add pagination or virtual scrolling for months with many items.

### P4-15: Notification Polling Should Use SSE/WebSocket
- **File:** `frontend/src/components/layout/Header.tsx` (lines 45-50)
- **Issue:** Polls every 30 seconds. Inefficient for real-time notifications.
- **Fix:** Replace with Server-Sent Events or WebSocket connection. Lower priority.

---

## 6. Phase 5: Infrastructure & Observability

> **Priority:** MEDIUM — Production readiness
> **Estimated items:** 10

### P5-01: Add Health Checks to All Services
- **File:** `docker-compose.yml`
- **Fix:** Add healthcheck configs for: backend (`/health`), nats (`nats-server --signal health`), minio (`mc ready`), litellm (`/health`), valkey (`redis-cli ping`), qdrant (`/readyz`), browser-worker (`/health`).

### P5-02: Use service_healthy Instead of service_started
- **File:** `docker-compose.yml`
- **Issue:** Most `depends_on` use `service_started`. Services may connect before dependencies are ready.
- **Fix:** Switch to `condition: service_healthy` for all critical dependencies.

### P5-03: Add Missing Prometheus Scrape Targets
- **File:** `observability/prometheus/prometheus.yml`
- **Issue:** Missing jobs for postgres, valkey, minio, qdrant.
- **Fix:** Add scrape configs for all monitored services.

### P5-04: Fix OTel Trace Export
- **File:** `observability/otel-collector/otel-collector-config.yaml`
- **Issue:** Traces export to `debug` only (console). Not queryable.
- **Fix:** Add Jaeger or Grafana Tempo exporter.

### P5-05: Add Traefik Security Headers Middleware
- **File:** `traefik/traefik.yml`
- **Issue:** No security headers (X-Frame-Options, CSP, HSTS, etc.).
- **Fix:** Add headers middleware with production security headers.

### P5-06: Next.js Remote Image Patterns
- **File:** `frontend/next.config.ts`
- **Issue:** `minio.markai.local` won't resolve in Docker. localhost allowed.
- **Fix:** Update to match actual MinIO hostnames in each environment.

### P5-07: Next.js Build-Time Env Validation
- **File:** `frontend/next.config.ts`
- **Issue:** Falls back to `localhost:8000` if `NEXT_PUBLIC_API_URL` not set. Silent misconfiguration.
- **Fix:** Add build-time check that fails if required env vars are missing.

### P5-08: NATS Stream Configuration
- **Issue:** No explicit stream/consumer configuration in NATS config. Created at runtime by application.
- **Fix:** Add init script or startup hook that validates stream configuration on boot.

### P5-09: Docker Build Cache Optimization
- **Files:** All Dockerfiles
- **Issue:** No `.dockerignore`, pip requirements not cached separately.
- **Fix:** Add `.dockerignore` files and restructure COPY commands to leverage build cache.

### P5-10: Agents Dockerfile Missing Playwright
- **File:** `agents/Dockerfile`
- **Issue:** No `playwright install --with-deps chromium` command. Browser-dependent operations will fail inside the agents container.
- **Fix:** Add playwright install step (or ensure browser-worker handles all browser ops).

---

## 7. Phase 6: Pipeline Completeness

> **Priority:** MEDIUM — Completes the content factory vision
> **Estimated items:** 6

### P6-01: Evaluation → Adaptation Chaining
- **File:** `agents/worker.py` (lines 146-151)
- **Issue:** No auto-chain from evaluation to adaptation workflow. These are standalone.
- **Fix:** Add `"evaluation": "adaptation.trigger"` to CHAIN_NEXT dict.

### P6-02: Product Intel Integration
- **Issue:** Product intelligence workflow is standalone, never auto-triggered.
- **Fix:** Consider triggering after research: `"research": ["strategy.trigger", "product_intel.trigger"]` (parallel).

### P6-03: Feedback Loop from Adaptation to Planning
- **Issue:** After adaptations are approved, no new content is generated.
- **Fix:** Add chain from adaptation completion back to content.generate for affected calendar items.

### P6-04: Multilingual Content Generation
- **Issue:** Prompts mention English/French/Creole but never request multilingual output. All content generated in English only.
- **Fix:** Add language parameter to content workflow. Generate bilingual captions (English + French/Kreol) per platform strategy.

### P6-05: Idempotency for NATS Messages
- **Issue:** If a message is reprocessed after crash, duplicate agent_runs are created.
- **Fix:** Add `idempotency_key` field to agent_runs with unique constraint. Check before creating.

### P6-06: LLM Output Schema Validation
- **Issue:** No validation that LLM JSON responses match expected schema. Partial/malformed JSON fails silently.
- **Fix:** Add Pydantic model validation for all LLM outputs with clear error messages.

---

## 8. Benchmark Content Review

Benchmark content was generated by Claude Opus 4.6 using direct reasoning and web research for the **Healthspan** brand in Mauritius. These outputs serve as the gold standard to compare against MARKAI's automated pipeline outputs.

### Files in `review/`

| File | Description | Size |
|------|-------------|------|
| `benchmark_research_report.md` | Market research: 6 competitors, 4 target segments, social media stats, SWOT analysis | 28 KB |
| `benchmark_strategy.md` | Full marketing strategy: 6 content pillars, platform tactics, posting schedule, KPIs | 23 KB |
| `benchmark_content_calendar.md` | 14-day calendar with 42 posts across Instagram, Facebook, YouTube | 48 KB |
| `content/instagram_post_1.md` | Wellness tips carousel with moringa, turmeric, coconut | 5 KB |
| `content/instagram_post_2.md` | Product lifestyle shot concept "Golden Hour Veranda" | 5 KB |
| `content/facebook_post_1.md` | Diabetes prevention community awareness (1 in 5 stat) | 7 KB |
| `content/youtube_short_1.md` | 60-second Golden Coco Latte recipe script with timestamps | 10 KB |
| `content/README.md` | Overview, calendar mapping, quality criteria | 6 KB |

### Benchmark Quality Characteristics

These are the standards the MARKAI pipeline should match:

1. **Localization Depth** — References 15+ specific Mauritian locations, 10+ Creole terms, all 4 major communities, local health statistics
2. **Data-Driven** — Real competitor names, actual social media penetration numbers, GDP and health expenditure data
3. **Platform-Specific** — Different tone, length, hashtag strategy per platform (not one-size-fits-all)
4. **Visual Direction** — Detailed art direction for every piece (camera angles, colors, backgrounds, staging)
5. **Actionable** — Every recommendation includes a specific implementation step, not just high-level advice
6. **Trilingual** — English primary with natural French/Kreol integration (not forced translations)

### How to Compare

After running the Content Factory pipeline for Healthspan:
1. Open Intelligence tab → View Research Report → Compare against `review/benchmark_research_report.md`
2. View Strategy Report → Compare against `review/benchmark_strategy.md`
3. View Content Calendar → Compare against `review/benchmark_content_calendar.md`
4. View generated content pieces → Compare against files in `review/content/`

Key comparison criteria:
- Does the automated output identify the same competitors?
- Are the target audience segments similar?
- Is the content calendar's platform mix and frequency comparable?
- Is localization as deep (Creole terms, local references, cultural sensitivity)?
- Are content pieces actionable and post-ready?

---

## 9. Files Changed Summary

### Phase 1 Changes (14 items)
| File | Change |
|------|--------|
| `litellm/config.yaml` | Fix model names |
| `.env` | Fix MINIO_ENDPOINT, add FRONTEND_URL |
| `traefik/traefik.yml` | Production ACME URL, secure dashboard, real email |
| `agents/workflows/planning/nodes.py` | Fix field mapping for calendar items |
| `agents/workflows/strategy/nodes.py` | Fix data field: output_payload |
| `agents/workflows/planning/nodes.py` | Fix data field: output_payload |
| `agents/workflows/content/nodes.py` | Add website_url to brand config query |
| `agents/shared/tools/database.py` | Fix store_research to use output_payload |
| `docker-compose.yml` | Add health checks for all services |
| `backend/app/api/v1/webhooks.py` | Use secrets.compare_digest |
| `agents/shared/tools/fabric.py` | Implement or remove BC image lookup |
| `agents/worker.py` | Fix chain failure handling (NAK on publish fail) |
| `backend/app/config.py` | Add startup validation for default secrets |

### Phase 2 Changes (12 items)
| File | Change |
|------|--------|
| `backend/app/api/v1/intelligence.py` | Fix N+1 query, add JSON parse error handling |
| `backend/app/api/v1/brands.py` | Add transaction rollback, fix file extension |
| `backend/app/services/brand_service.py` | Audit all JSONB writes for flag_modified |
| `backend/app/scheduler/bc_sync.py` | Add unique constraint, advisory locks |
| `backend/app/auth/entra.py` | Add asyncio.Lock for token cache |
| `backend/app/api/v1/analytics.py` | Add NULL checks |
| `agents/shared/tools/database.py` | Add product_id to calendar items, fix is_current |
| `backend/app/api/v1/approvals.py` | Add total count to response |
| `backend/app/services/fabric_service.py` | Add conn NULL check |

### Phase 3 Changes (8 items)
| File | Change |
|------|--------|
| `backend/app/services/fabric_service.py` | Table name whitelist |
| `backend/app/auth/entra.py` | OData escaping fix |
| `agents/workflows/*/nodes.py` | Input sanitization for prompts |
| `backend/app/main.py` | Sanitize exception logs |
| `.env`, `frontend/.env.local` | Move to secrets management |
| `observability/grafana/grafana.ini` | Change default credentials |
| `observability/loki/loki-config.yaml` | Enable auth |

### Phase 4 Changes (15 items)
| File | Change |
|------|--------|
| `frontend/src/components/content/KanbanBoard.tsx` | Responsive grid |
| `frontend/src/app/content/page.tsx` | Error toasts, AbortController |
| `frontend/src/components/layout/Header.tsx` | Accessibility labels, breadcrumb truncate |
| `frontend/src/components/layout/BrandSwitcher.tsx` | Error toast |
| `frontend/src/components/content/CalendarView.tsx` | Responsive height, overflow |
| `frontend/src/components/brand/BrandOnboarding.tsx` | Wire in or remove |
| `frontend/src/components/brand/CompetitorTracker.tsx` | Wire in or remove |
| `frontend/src/app/approvals/page.tsx` | Refetch after action |
| `frontend/src/components/brand/BrandForm.tsx` | URL validation |
| `frontend/src/app/brands/page.tsx` | Retry button on error |
| `frontend/src/app/settings/page.tsx` | Responsive select |
| `frontend/src/components/approval/ApprovalActions.tsx` | Responsive flex |
| `frontend/src/app/brands/[id]/page.tsx` | Split into tab components |

### Phase 5 Changes (10 items)
| File | Change |
|------|--------|
| `docker-compose.yml` | Health checks, service_healthy, depends_on |
| `observability/prometheus/prometheus.yml` | Add scrape targets |
| `observability/otel-collector/otel-collector-config.yaml` | Add trace exporter |
| `traefik/traefik.yml` | Security headers middleware |
| `frontend/next.config.ts` | Fix remote patterns, env validation |
| `agents/Dockerfile` | Add playwright install (if needed) |
| All Dockerfiles | Add .dockerignore, cache optimization |

### Phase 6 Changes (6 items)
| File | Change |
|------|--------|
| `agents/worker.py` | Add evaluation→adaptation chain, idempotency |
| `agents/workflows/content/nodes.py` | Multilingual support |
| All workflow nodes | LLM output schema validation |

---

## Approval Requested

**Total remediation items: 65**
- Phase 1 (Critical): 14 items
- Phase 2 (Data Flow): 12 items
- Phase 3 (Security): 8 items
- Phase 4 (Frontend UX): 15 items
- Phase 5 (Infrastructure): 10 items
- Phase 6 (Pipeline): 6 items

**Benchmark content** is ready for review in `review/` folder.

Please review this plan and let me know:
1. Which phases to proceed with (recommend P1 + P2 first)
2. Any items to deprioritize or skip
3. Any additional items to add
