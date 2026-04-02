# MARKAI — COMPREHENSIVE CODEBASE AUDIT REPORT

**Date:** 2026-04-02
**Scope:** Full codebase audit — security, dependencies, AI/ML, database, frontend, infrastructure, testing, code quality
**Method:** Automated multi-agent audit with web-verified dependency checks
**Audited Against:** `PROJECT_AUDIT_PROMPT.md` (generated 2026-04-02)

---

## 1. EXECUTIVE SUMMARY

### Overall Grade: **D+** (Significant Issues)

The MarkAI platform demonstrates strong architectural vision — clean service separation, enterprise SSO, full observability stack, and well-designed RBAC. However, the audit uncovered **critical security vulnerabilities**, **supply chain risks**, **zero meaningful test coverage**, and **widespread schema drift** that collectively present unacceptable risk for a production system.

### Findings by Severity

| Severity | Count | Key Themes |
|----------|-------|------------|
| **CRITICAL** | 16 | Supply chain CVE, committed secrets, SSRF, missing auth on internal services, no security headers, XSS vectors |
| **HIGH** | 37 | OData injection, JWKS stale cache, unbounded parameters, privilege escalation, N+1 queries, schema mismatches, role enforcement gaps |
| **MEDIUM** | 39 | CORS wildcards, flat Docker network, missing pagination, no error boundaries, payload injection, CI gaps |
| **LOW** | 38 | Touch targets, ARIA gaps, duplicate constants, minor config drift, missing healthchecks |
| **INFO** | 12 | Positive findings (parameterized SQL, good patterns), testing infrastructure gaps |

**Total: 142 findings** (16 critical, 37 high, 39 medium, 38 low, 12 info)

### Top 5 Critical Actions Required

1. **[DEP-C1] Upgrade LiteLLM immediately** — CVE-2026-33634 (CVSS 9.4) supply chain attack on v1.82.x; upgrade Docker image to v1.83.0+
2. **[SEC-C1] Rotate ALL production secrets** — `.env` file contains live Azure AD, OpenAI, Gemini, Postgres, MinIO, Fabric, n8n credentials on disk
3. **[INFRA-C2] Add authentication to NATS** — Any container on the Docker network can publish/subscribe to any subject without credentials
4. **[AI-C2] Add SSRF protection** — Browser worker, agent tools, and Gemini service fetch arbitrary URLs without blocking internal/private IP ranges
5. **[FE-C3] Sanitize ReactMarkdown output** — AI-generated content rendered without HTML sanitization enables stored XSS

---

## 2. DEPENDENCY AUDIT TABLE

### Critical Vulnerabilities

| Package | Project Version | Latest Stable | CVE / Advisory | Action |
|---------|----------------|---------------|----------------|--------|
| **LiteLLM** (Docker) | v1.82.3-stable.patch.2 | v1.83.0+ | **CVE-2026-33634 (CVSS 9.4)** — supply chain attack, credential harvesting backdoor in v1.82.7-1.82.8 | **URGENT: Upgrade Docker image** |
| **Traefik** | v3.6 | v3.6.12 | **CVE-2026-33433, CVE-2026-33186** | **Upgrade immediately** |
| **PyJWT** | unpinned | 2.12.1 | **CVE-2026-32597 (HIGH)** — `crit` header bypass | **Pin >= 2.12.0** |
| **Next.js** | ^16.2.1 | 16.2.2 | CVE-2026-23864, CVE-2026-27979 (DoS, patched in 16.1.5/16.1.7) | Verify lock file >= 16.2.1 |
| **MinIO** (Docker) | RELEASE.2025-01-20 | RELEASE.2026-03-12 | Privilege escalation (patched 2025-10-15); **repo archived Feb 2026** | Upgrade; evaluate alternatives |

### Major Version Gaps

| Package | Project Version | Latest | Gap |
|---------|----------------|--------|-----|
| TypeScript | ^5.7.2 | 6.0.2 | 1 major behind |
| ESLint | ^9.17.0 | 10.1.0 | 1 major behind |
| n8n | 1.82.1 | 2.14.1 | 1 major behind |
| PostgreSQL | 16-alpine | 17.9 / 18.3 | 1-2 major behind |
| next-auth | ^4.24.11 | Auth.js v5 (production-ready) | Migration recommended |

### Version Mismatches

| Issue | Detail |
|-------|--------|
| tenacity | Backend `>=8.2` vs Agents `>=9.0` — align to `>=9.0` |
| bcrypt | `>=4.0` but 5.0.0 is available (adds Python 3.14 + ARM) |
| Loki/Promtail | 3.6.7 → 3.7.1 available |
| OTel Collector | 0.147.0 → 0.149.0 available |

### Up-to-Date (No Action)

fastapi (0.135.3), react (19.2.4), sqlalchemy (2.0.48), pydantic (2.12.5), langgraph (1.1.0), langchain-core (1.2.24), langchain-openai (1.1.11), asyncpg (0.31.0), alembic (1.18.4), httpx (0.28.1), nats-py (2.14.0), qdrant-client (1.17.1), playwright (1.58.0), Pillow (12.2.0), apscheduler (3.11.2), zustand (5.0.12), recharts (3.8.1), tailwindcss (4.2.2), Prometheus (v3.10.0), all Radix UI packages (within semver range).

### Deprecated/Abandoned Concerns

- **MinIO OSS**: Repository archived Feb 2026; shifted to commercial AIStor. Evaluate SeaweedFS or Garage.
- **slowapi** (0.1.9): No releases in 12+ months; low maintenance.
- **next-auth v4**: Maintenance mode; active development is Auth.js v5.

---

## 3. AI/ML MODEL AUDIT

### Models in Use

| Category | Model | Via | Config Location |
|----------|-------|-----|-----------------|
| Text (primary) | gpt-5.4 | LiteLLM proxy | litellm/config.yaml |
| Text (fast) | gpt-5.4-mini | LiteLLM proxy | litellm/config.yaml |
| Image | dall-e-4 | LiteLLM proxy | litellm/config.yaml |
| Vision | gemini-2.5-flash | google-genai SDK | gemini_service.py |
| Web search | gemini-2.5-flash (grounding) | google-genai SDK | web_search.py |
| Embeddings | text-embedding-3-small | LiteLLM proxy | litellm/config.yaml |

### Integration Quality

| Aspect | Status | Detail |
|--------|--------|--------|
| Error handling | Partial | `chat_completion()` has retry logic for 429s; Gemini service catches API errors. But raw exceptions leak to API responses in intelligence.py |
| Token tracking | **Non-functional** | `_total_tokens` field exists but no workflow ever populates it. Zero visibility into per-workflow LLM spend |
| Cost tracking | **Missing** | No `max_budget`, `rpm_limit`, or `tpm_limit` in LiteLLM config |
| Rate limiting | **Missing** | No proactive rate limiting on agent LLM calls; a brand activation can chain hundreds of calls |
| Output validation | **Unused** | `validate_llm_output()` exists in llm.py but is never called by any workflow node |
| Prompt injection defense | **Incomplete** | 9 patterns in sanitize.py; missing Unicode homoglyphs, ChatML close tags, XML injections, zero-width chars, role delimiters |
| Model fallbacks | **Missing** | No fallback chains configured in LiteLLM |

---

## 4. ALL FINDINGS BY SEVERITY

### CRITICAL (16)

| ID | Domain | File | Lines | Description | Impact | Fix Effort |
|----|--------|------|-------|-------------|--------|------------|
| DEP-C1 | Dependency | docker-compose.yml | 263 | LiteLLM v1.82.3 — CVE-2026-33634 supply chain attack (CVSS 9.4) | Credential harvesting, persistent backdoor | Low — change image tag |
| SEC-C1 | Security | .env | 1-77 | Production secrets committed on disk (Azure AD, OpenAI, Gemini, Postgres, MinIO, Fabric, n8n, NextAuth) | Full compromise of all integrated services | Medium — rotate all secrets, add pre-commit hook |
| SEC-C2 | Security | backend/app/services/minio_service.py | 19-24 | `secure=False` hardcoded — plaintext credentials over HTTP | Credential sniffing in non-localhost deployments | Low — make configurable |
| SEC-C3 | Security | backend/app/api/v1/providers.py | 73-82 | `/api/v1/providers/active` has no authentication — exposes active AI model config | Information disclosure, API probing | Low — add auth dependency |
| AI-C1 | AI/ML | agents/shared/sanitize.py | 6-16 | Incomplete prompt injection sanitization — missing Unicode, ChatML, XML, zero-width char patterns | Prompt injection via brand names, crawled websites, product descriptions | Medium — expand pattern list, add NFKC normalization |
| AI-C2 | AI/ML | agents/shared/tools/browser.py | 74-102 | No SSRF protection on URL fetching — no private IP range blocking | SSRF to cloud metadata, internal Docker services, databases | Medium — add URL validation function |
| AI-C3 | AI/ML | agents/worker.py | 132-144 | `custom_prompt` passed raw to image generation API without sanitization | Arbitrary image generation bypassing content safety | Low — apply sanitize_for_prompt() |
| INFRA-C1 | Infrastructure | scripts/vps-redeploy.sh | 69 | `docker volume rm markai_pgdata markai_qdrant_data` — destructive wipe without backup | Permanent data loss on every redeploy | Medium — add backup step |
| INFRA-C2 | Infrastructure | docker-compose.yml | 132-150 | NATS has no authentication — any container can publish/subscribe | Malicious workflow injection, data exfiltration | Low — add `--auth` flag |
| INFRA-C3 | Infrastructure | browser-worker/app/main.py | 104-170 | Browser worker endpoints have zero authentication | SSRF via any service on Docker network | Medium — add API key check |
| INFRA-C4 | Infrastructure | notifications/app/main.py | 111-114 | SSE `/stream/{user_id}` has no authentication | Any client can subscribe to any user's notifications | Medium — add JWT validation |
| DB-C1 | Database | db/init.sql | 376 | `audit_log.user_id REFERENCES users(id)` — no ON DELETE clause (defaults RESTRICT) | Users with audit entries cannot be deleted | Low — add ON DELETE SET NULL |
| DB-C2 | Database | backend/alembic/versions/ | — | Empty — no migration history committed | Schema drift undetectable, no rollback capability | Medium — generate baseline |
| DB-C3 | Database | Multiple models | — | Missing `back_populates` on User↔Approvals, User↔PromptVersions, Brand↔Content, Brand↔EngagementMetrics | ORM returns stale/empty data on reverse navigation | Medium — add relationships |
| FE-C1 | Frontend | frontend/next.config.ts | 1-25 | No security headers (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) | Clickjacking, MIME-sniffing, XSS | Low — add headers() config |
| FE-C2 | Frontend | Multiple components | — | User/AI-supplied image URLs rendered via raw `<img src>` bypassing Next.js Image whitelist | XSS via javascript: protocol, data URIs | Medium — sanitize URLs |
| FE-C3 | Frontend | components/ui/safe-render.tsx | 43-49 | ReactMarkdown renders AI output without HTML sanitization | Stored XSS via prompt injection or DB compromise | Low — add rehype-sanitize |

### HIGH (37)

| ID | Domain | File | Lines | Description |
|----|--------|------|-------|-------------|
| DEP-H1 | Dependency | docker-compose.yml | — | Traefik v3.6 has CVE-2026-33433, CVE-2026-33186 — upgrade to v3.6.12 |
| DEP-H2 | Dependency | backend/pyproject.toml | — | PyJWT unpinned — CVE-2026-32597 (`crit` header bypass). Pin >= 2.12.0 |
| DEP-H3 | Dependency | docker-compose.yml | — | MinIO RELEASE.2025-01-20 — privilege escalation vuln patched in 2025-10-15; repo archived |
| DEP-H4 | Dependency | — | — | TypeScript 5.x is 1 major version behind (6.0.2 available) |
| DEP-H5 | Dependency | — | — | ESLint 9.x is 1 major version behind (10.1.0 available) |
| DEP-H6 | Dependency | — | — | n8n 1.82.1 is 1 major version behind (2.14.1 available) |
| DEP-H7 | Dependency | — | — | next-auth v4 should migrate to Auth.js v5 |
| DEP-H8 | Dependency | — | — | tenacity version mismatch: backend >=8.2 vs agents >=9.0 |
| SEC-H1 | Security | backend/app/auth/entra.py | 149-175 | OData injection in `get_graph_users_by_ids` — user_ids not sanitized |
| SEC-H2 | Security | backend/app/auth/entra.py | 16-21 | JWKS client cached forever, never auto-rotates — auth outage on key rotation |
| SEC-H3 | Security | backend/app/auth/entra.py | 178-203 | `user_id` interpolated into Graph API URL path without UUID validation |
| SEC-H4 | Security | backend/app/api/v1/analytics.py | 60-95 | `days` parameter unbounded — DoS via expensive DB scan |
| SEC-H5 | Security | backend/app/api/v1/brands.py | 424-455 | Public logo endpoint enables brand_id enumeration |
| SEC-H6 | Security | backend/app/api/v1/products.py | 311-377 | `batch-fetch-images` has no limit on `product_ids` list — unbounded API calls |
| SEC-H7 | Security | backend/app/api/v1/webhooks.py | 21-115 | No replay protection on webhook (no timestamp/nonce) |
| SEC-H8 | Security | backend/app/api/v1/users.py | 76-140 | Admin can grant admin to anyone — no separation of duties, no audit trail |
| AI-H1 | AI/ML | agents/shared/tools/storage.py | 52-69 | No path traversal protection on MinIO object names |
| AI-H2 | AI/ML | agents/shared/tools/database.py | 607-623 | `execute_query` accepts arbitrary SQL strings |
| AI-H3 | AI/ML | agents/shared/llm.py | 41-67 | Token/cost tracking non-functional — `_total_tokens` never populated |
| AI-H4 | AI/ML | agents/shared/llm.py + litellm/config.yaml | — | No rate limiting on agent LLM calls; no `rpm_limit`/`tpm_limit` |
| AI-H5 | AI/ML | agents/shared/tools/fabric.py | 77-106 | `execute_sql` accepts arbitrary SQL to external Business Central DB |
| AI-H6 | AI/ML | agents/shared/llm.py | 179-203 | `validate_llm_output()` exists but is never called — malformed output cascades |
| AI-H7 | AI/ML | backend/app/api/v1/intelligence.py | 690 | Raw exception messages returned to API callers |
| DB-H1 | Database | init.sql / prompt_version.py | 237 / 34-35 | Numeric precision mismatch: SQL NUMERIC(5,4) vs model Numeric(7,4) |
| DB-H2 | Database | init.sql / engagement.py | 285 / 27 | Channel width mismatch: SQL VARCHAR(50) vs model String(255) |
| DB-H3 | Database | backend/app/services/content_service.py | 15-29 | `list_content()` missing eager loading — N+1 queries |
| DB-H4 | Database | backend/app/scheduler/publish_checker.py | 27-48 | N+1 query: iterates calendar items then queries content individually |
| DB-H5 | Database | backend/app/scheduler/engagement_puller.py | 56-75 | N+1 query: iterates all published items with separate content queries |
| DB-H6-H10 | Database | Multiple models | — | 5 additional column width mismatches (campaign objective, agent_run fields, audit_log fields, scheduled_job_log, prompt_version a_b_group) |
| INFRA-H1 | Infrastructure | docker-compose.yml | — | No log rotation on 10 of 13 services |
| INFRA-H2 | Infrastructure | docker-compose.yml | 123 | Valkey password leaked in healthcheck command (visible in `docker inspect`) |
| INFRA-H3 | Infrastructure | Multiple Dockerfiles | — | No HEALTHCHECK in 3 of 5 Dockerfiles |
| INFRA-H4 | Infrastructure | frontend/Dockerfile | 21-23 | Azure AD Client ID baked into image layer via ENV |
| INFRA-H5 | Infrastructure | notifications/.dockerignore | — | Missing `.env.*` glob pattern |
| INFRA-H6 | Infrastructure | scripts/seed-dev.py | 196 | No auth headers, no environment guard (could seed production) |
| INFRA-H7 | Infrastructure | docker-compose.yml | 26, 437 | Docker socket mounted on Traefik + Promtail — container escape risk |
| FE-H1 | Frontend | Multiple pages | — | Only 4 of 21 pages enforce roles — viewers can access brand creation, approvals, prompts, providers |
| FE-H2 | Frontend | frontend/src/lib/hooks.ts | 13-18 | Frontend role levels (0/1/2/3) differ from backend (10/60/80/100) |
| FE-H3 | Frontend | — | — | Zero React Error Boundaries — render crash white-screens entire app |
| FE-H4 | Frontend | frontend/src/lib/api.ts | — | No CSRF protection for state-mutating operations |

### MEDIUM (39)

| ID | Domain | Description |
|----|--------|-------------|
| SEC-M1 | Security | Missing security headers (HSTS, CSP, X-Content-Type-Options) on backend |
| SEC-M2 | Security | CORS `allow_methods=["*"]` and `allow_headers=["*"]` |
| SEC-M3 | Security | Incomplete credential validation at startup (missing N8N_WEBHOOK_SECRET, LITELLM_MASTER_KEY, VALKEY_PASSWORD, FRONTEND_URL) |
| SEC-M4 | Security | Rate limiter IP-based `get_remote_address` — bypassable behind proxy |
| SEC-M5 | Security | Prometheus `/metrics` endpoint exposed without auth |
| SEC-M6 | Security | Duplicate PUT/PATCH endpoints with identical logic (users.py, calendar.py) |
| SEC-M7 | Security | Error messages leak internal exception details |
| SEC-M8 | Security | Content-type from upload not validated against magic bytes |
| SEC-M9 | Security | SVG uploads allowed without sanitization — stored XSS |
| AI-M1 | AI/ML | MemorySaver checkpointer uses in-memory storage — lost on restart |
| AI-M2 | AI/ML | Shared httpx client singletons have no lifecycle management |
| AI-M3 | AI/ML | No input length validation on NATS payloads — extra keys injected into state |
| AI-M4 | AI/ML | Strategy auto-approve bypassable via payload injection (`auto_approve: true`) |
| AI-M5 | AI/ML | `remaining_queue` can grow unbounded in content chaining |
| AI-M6 | AI/ML | Gemini API key could be exposed if client repr is logged |
| AI-M7 | AI/ML | No max tokens guard on LLM input size |
| DB-M1 | Database | Missing CHECK constraints in Pydantic schemas for enum-like fields |
| DB-M2 | Database | Notification model missing `ondelete="CASCADE"` (present in SQL) |
| DB-M3 | Database | 16 FK declarations in models lack `ondelete=` that SQL has — Alembic drift risk |
| DB-M4 | Database | 7 `created_by` FK references have no ON DELETE clause in SQL |
| DB-M5 | Database | bc_sync.py commits per-item instead of batching |
| DB-M6 | Database | `content_generation_days_ahead` missing from settings API `_VALID_SETTING_KEYS` |
| INFRA-M1 | Infrastructure | Single flat `markai-net` network — browser-worker can reach postgres |
| INFRA-M2 | Infrastructure | No volume backup strategy for 10 named volumes |
| INFRA-M3 | Infrastructure | CI pipeline missing Docker build test, security scanning, coverage reporting |
| INFRA-M4 | Infrastructure | Prometheus missing scrape targets for browser-worker, notifications, n8n, postgres |
| INFRA-M5 | Infrastructure | Loki auth disabled |
| INFRA-M6 | Infrastructure | Grafana admin password weak default (`change-me-grafana`) |
| INFRA-M7 | Infrastructure | Traefik dashboard may fail open if `TRAEFIK_DASHBOARD_AUTH` empty |
| INFRA-M8 | Infrastructure | Teams webhook payload injection — unsanitized fields in MessageCard |
| INFRA-M9 | Infrastructure | CSP allows `unsafe-inline` and `unsafe-eval` |
| FE-M1 | Frontend | No pagination component — client-side data truncation with hardcoded limits |
| FE-M2 | Frontend | Custom DOM events for brand switching — brittle, ignored by most pages |
| FE-M3 | Frontend | No test framework installed (no Jest, Vitest, Playwright, Cypress) |
| FE-M4 | Frontend | Missing loading/disabled states on mutation buttons — double-submit risk |
| FE-M5 | Frontend | Notification polling creates 401 loop on expired sessions |
| FE-M6 | Frontend | AbortController not used consistently across pages |
| FE-M7 | Frontend | `useEffect` dependency array issues in audit page |
| FE-M8 | Frontend | No SWR/React Query — all fetching is manual useEffect with no caching/dedup |

### LOW (38)

| ID | Domain | Description |
|----|--------|-------------|
| SEC-L1 | Security | Health endpoint returns no dependency status |
| SEC-L2 | Security | System health endpoint leaks dependency error messages |
| SEC-L3 | Security | `_graph_token_lock` created at module level — event loop risk on older Python |
| SEC-L4 | Security | Global exception handler sanitization is keyword-based and incomplete |
| SEC-L5 | Security | `approvals.py` parameter shadowing (`status` vs `status_filter`) |
| AI-L1 | AI/ML | Non-idiomatic `state.get("errors") or []` pattern across all workflow nodes |
| AI-L2 | AI/ML | LiteLLM config has no model fallback chain |
| AI-L3 | AI/ML | Duplicate sanitization code between agents and backend |
| AI-L4 | AI/ML | `parse_llm_json` single-key dict unwrapping is fragile |
| AI-L5 | AI/ML | Rate limiting only on 2 of 10+ intelligence endpoints; workflow triggers unprotected |
| DB-L1-L5 | Database | Raw SQL properly parameterized (positive — no injection found) |
| DB-L6 | Database | Product model currency default mismatch (SQL 'MUR' vs model None) |
| DB-L7 | Database | `app_settings` table has no SQLAlchemy model |
| DB-L8 | Database | Pool size may be tight under concurrent scheduler + API load |
| DB-L9 | Database | CalendarItem.priority missing CHECK constraint in model |
| DB-L10 | Database | Notification model missing default `channel` value |
| INFRA-L1 | Infrastructure | No CPU limits on any container |
| INFRA-L2 | Infrastructure | Prometheus has no Alertmanager integration — alerts fire but nobody receives them |
| INFRA-L3 | Infrastructure | Hardcoded VPS hostname in multiple files |
| INFRA-L4 | Infrastructure | `NEXT_PUBLIC_AZURE_AD_CLIENT_ID` missing from `.env.example` |
| INFRA-L5 | Infrastructure | `.env.example` has duplicate `# Scheduler` comment |
| INFRA-L6 | Infrastructure | Grafana dashboard JSON referenced but file doesn't exist |
| INFRA-L7 | Infrastructure | OTel Collector memory limiter (1024 MiB) exceeds container limit (256 MB) |
| INFRA-L8 | Infrastructure | Prometheus missing healthcheck in compose |
| INFRA-L9 | Infrastructure | Grafana, Loki, Promtail, OTel-Collector missing healthchecks |
| FE-L1 | Frontend | Touch targets below 44px minimum (AI wand buttons 24px, edit/delete 28px) |
| FE-L2 | Frontend | No keyboard shortcuts for common actions |
| FE-L3 | Frontend | Missing ARIA labels/roles (calendar overlay, Kanban columns, form labels) |
| FE-L4 | Frontend | Duplicate constant definitions (CHANNEL_DISPLAY_NAMES, STATUS_COLORS in 4+ files) |
| FE-L5 | Frontend | `platformIcon()` missing mapping for "x" channel |
| FE-L6 | Frontend | Hardcoded fake engagement numbers in social previews |
| FE-L7 | Frontend | next-auth Session type augmentation missing `user.role` |
| FE-L8 | Frontend | ConfirmDialog doesn't reset loading state on external close |
| FE-L9 | Frontend | `any` type usage despite strict TypeScript config |

### INFO / POSITIVE FINDINGS (12)

| ID | Description |
|----|-------------|
| INFO-1 | All raw SQL uses parameterized queries via `text()` — **no SQL injection found** |
| INFO-2 | Intelligence module properly sanitizes user input before LLM prompts |
| INFO-3 | `secrets.compare_digest()` used for webhook verification (timing-safe) |
| INFO-4 | Frontend channel list exactly matches backend `ALL_CHANNELS` |
| INFO-5 | Fabric service uses table name whitelisting — strong defense |
| INFO-6 | Connection pool configured with `pool_pre_ping=True` for stale connection handling |
| INFO-7 | `expire_on_commit=False` correctly set for async SQLAlchemy sessions |
| INFO-8 | JSONB mutation detection properly handled via `flag_modified` |
| INFO-9 | `bc_sync.py` uses `asyncio.Lock()` to prevent overlapping syncs |
| INFO-10 | Multi-stage Docker builds with non-root users across all services |
| INFO-11 | Memory limits set on all containers (CPU limits missing per INFRA-L1) |
| INFO-12 | Job trigger endpoint validates against registered APScheduler jobs |

---

## 5. PRE-LOADED ISSUES VERIFICATION

| Pre-loaded ID | Status | Audit Finding ID | Notes |
|---------------|--------|------------------|-------|
| PRE-001 | **CONFIRMED** | SEC-C1 | `.env` on disk with live production secrets. `.gitignore` has `.env` entry, preventing future commits, but secrets are exposed |
| PRE-002 | **CONFIRMED** | SEC-M2 | CORS `allow_methods=["*"]`, `allow_headers=["*"]` at main.py:101-107 |
| PRE-003 | **CONFIRMED** | SEC-M1 | No HSTS, CSP, X-Content-Type-Options, X-Frame-Options headers |
| PRE-004 | **CONFIRMED** | SEC-C2 | `secure=False` hardcoded in minio_service.py:22; browser-worker config defaults False |
| PRE-005 | **CONFIRMED** | SEC-M3 | Only checks SECRET_KEY, POSTGRES_PASSWORD, MINIO_SECRET_KEY; misses 6+ other secrets |
| PRE-006 | **CONFIRMED** | DB-C2 | `backend/alembic/versions/` is empty — zero migrations |
| PRE-007 | **CONFIRMED** | INFRA-C1 | `vps-redeploy.sh` line 69 wipes pgdata + qdrant_data volumes |
| PRE-008 | **CONFIRMED** | FE-M3 | No test framework installed in frontend |
| PRE-009 | **CONFIRMED** | — | ~1-2% overall coverage (6 test files, 256 lines total) |
| PRE-010 | **CONFIRMED** | SEC-H1 | OData injection in `get_graph_users_by_ids` (entra.py:149-175); `search_graph_users` is safe |
| PRE-011 | **CONFIRMED** | SEC-H7 | No HMAC, no replay protection on webhook. Static secret comparison is timing-safe (good) |
| PRE-012 | **CONFIRMED** | SEC-M4 | `default_limits=["120/minute"]` with IP-based key extraction |
| PRE-013 | **CONFIRMED** | DB-H1 | init.sql NUMERIC(5,4) vs model Numeric(7,4) |
| PRE-014 | **CONFIRMED** | DB-L7 | No SQLAlchemy model for `app_settings` |
| PRE-015 | **CONFIRMED** | DB-H3 | `content_service.list_content()` missing `selectinload` |
| PRE-016 | **CONFIRMED** | SEC-H4 | `days` parameter unbounded in analytics |
| PRE-017 | **CONFIRMED** | SEC-M6 | calendar.py and users.py have duplicate PUT/PATCH |
| PRE-018 | **CONFIRMED** | SEC-L5 | `status` vs `status_filter` inconsistency; POST `/decide` duplicates PUT |
| PRE-019 | **CONFIRMED** | DB-C3 | Missing bidirectional relationships on 4 pairs |
| PRE-020 | **CONFIRMED** | DEP-H8 | tenacity >=8.2 (backend) vs >=9.0 (agents) |
| PRE-021 | **CONFIRMED** | SEC-H6 | `image_index` not bounds-checked in products.py |
| PRE-022 | **CONFIRMED** | SEC-H2 | JWKS client cached forever — no auto-rotation |
| PRE-023 | **CONFIRMED** | SEC-L4 | Keyword-based log sanitization misses sk-proj-..., AIza..., connection strings |
| PRE-024 | **CONFIRMED** | DB-C1 | audit_log.user_id no ON DELETE — blocks user deletion |
| PRE-025 | **CONFIRMED** | — | bcrypt installed but unused (auth is Entra ID SSO) |
| PRE-026 | **CONFIRMED** | — | All deletes are hard deletes (no soft delete pattern) |
| PRE-027 | **CONFIRMED** | DB-H2 | engagement_metrics.channel VARCHAR(50) in SQL vs String(255) in model |
| PRE-028 | **CONFIRMED** | — | No pre-commit hooks configured |
| PRE-029 | **CONFIRMED** | INFRA-M3 | No dependency scanning in CI/CD |
| PRE-030 | **CONFIRMED** | FE-M5 | Frontend uses polling instead of SSE for notifications |

**Result: All 30 pre-loaded issues CONFIRMED. 112 additional findings discovered beyond the pre-loaded list.**

---

## 6. SECURITY ASSESSMENT: **D**

| Category | Grade | Detail |
|----------|-------|--------|
| Authentication | B | Entra ID SSO is solid; JWKS stale cache and auto-user-creation are risks |
| Authorization | C- | Backend RBAC exists but frontend enforces roles on only 4 of 21 pages |
| Input Validation | C | Pydantic handles most cases; unbounded params, missing magic byte validation, SVG XSS |
| Secrets Management | F | Production secrets on disk; incomplete startup validation; 3 insecure defaults |
| Network Security | D | Single flat Docker network; NATS/browser-worker/notifications unauthenticated |
| Headers & CORS | D | No security headers; CORS wildcards on methods/headers |
| Supply Chain | D | Critical CVE in LiteLLM; Traefik CVEs; MinIO archived |
| XSS Prevention | D | ReactMarkdown unsanitized; SVG uploads; raw `<img src>` from user data |

---

## 7. PERFORMANCE ASSESSMENT: **C+**

| Category | Grade | Detail |
|----------|-------|--------|
| Database Queries | C- | 3 confirmed N+1 patterns; unbounded analytics; per-item commits in bc_sync |
| Caching | C | 5-min hard-coded TTLs; Valkey used but no frontend caching (no SWR/React Query) |
| Frontend Loading | C | No server-side pagination; manual useEffect everywhere; no request deduplication |
| Resource Management | B- | Memory limits on containers; no CPU limits; httpx clients never closed |
| Observability | B | Full stack deployed; missing scrape targets; alerts not delivered (no Alertmanager) |

---

## 8. CODE QUALITY ASSESSMENT: **B-**

| Category | Grade | Detail |
|----------|-------|--------|
| Architecture | A- | Clean service separation; well-designed RBAC; proper async patterns |
| Conventions | B+ | Consistent naming (snake_case Python, camelCase TS); Pydantic schemas throughout |
| Duplication | C | PUT/PATCH duplicates; sanitization code duplicated; constants duplicated 4+ times in frontend |
| Complexity | B- | worker.py (877 lines), brands.py (629 lines) are large but manageable |
| Dead Code | B+ | Only bcrypt is confirmed unused; no TODO/FIXME comments found |
| Type Safety | B | TypeScript strict mode enabled; one `any` usage; session type gap |

---

## 9. TESTING ASSESSMENT: **F**

| Metric | Value |
|--------|-------|
| Backend test files | 4 (118 lines) |
| Agent test files | 2 (138 lines) |
| Frontend test files | 0 |
| Estimated coverage | ~1-2% |
| Integration tests | 0 |
| E2E tests | 0 |
| CI coverage threshold | None |
| Test database fixtures | None |
| API test client | None |
| Pre-commit hooks | None |

**Untested:** 19 API route modules, 17 services, 14 models, 7 workflows, 8 agent tools, browser-worker (5 files), notifications (5 files), 21 frontend pages, 50 frontend components.

---

## 10. PHASED REMEDIATION PLAN

### Phase A: Critical Security (Week 1) — BLOCK DEPLOYMENTS UNTIL DONE

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| A1 | Upgrade LiteLLM Docker image to v1.83.0+ | 30 min | DEP-C1 |
| A2 | Upgrade Traefik to v3.6.12 | 30 min | DEP-H1 |
| A3 | Pin PyJWT >= 2.12.0 in backend/pyproject.toml | 15 min | DEP-H2 |
| A4 | Rotate ALL secrets in .env; add pre-commit hook blocking .env commits | 2h | SEC-C1 |
| A5 | Add authentication to NATS (`--auth` flag) | 1h | INFRA-C2 |
| A6 | Add API key auth to browser-worker endpoints | 2h | INFRA-C3 |
| A7 | Add JWT auth to notifications SSE stream | 2h | INFRA-C4 |
| A8 | Add auth to `/api/v1/providers/active` | 15 min | SEC-C3 |

### Phase B: Critical Bugs (Week 1-2)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| B1 | Add SSRF protection (block private IPs) to all URL fetches | 4h | AI-C2 |
| B2 | Sanitize `custom_prompt` in image regeneration | 30 min | AI-C3 |
| B3 | Expand prompt injection patterns; add NFKC normalization | 4h | AI-C1 |
| B4 | Add `rehype-sanitize` to ReactMarkdown | 1h | FE-C3 |
| B5 | Add security headers to next.config.ts | 1h | FE-C1 |
| B6 | Sanitize image URLs in frontend components | 2h | FE-C2 |
| B7 | Make MinIO `secure` configurable via settings | 30 min | SEC-C2 |
| B8 | Fix audit_log ON DELETE to SET NULL | 15 min | DB-C1 |
| B9 | Fix all `created_by` FK ON DELETE clauses | 1h | DB-M4 |

### Phase C: Dependency Updates (Week 2)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| C1 | Upgrade MinIO to >= RELEASE.2025-10-15 | 1h | DEP-H3 |
| C2 | Align tenacity to >=9.0 in both services | 15 min | DEP-H8 |
| C3 | Upgrade Loki + Promtail to 3.7.1 | 30 min | — |
| C4 | Upgrade OTel Collector to 0.149.0 | 30 min | — |
| C5 | Evaluate MinIO alternatives (SeaweedFS, Garage) for long-term | 4h | DEP-H3 |

### Phase D: High-Priority Fixes (Week 2-3)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| D1 | Fix OData injection in `get_graph_users_by_ids` (UUID validate) | 1h | SEC-H1 |
| D2 | Add JWKS auto-rotation (lifespan parameter or retry) | 2h | SEC-H2 |
| D3 | Cap `days` parameter in analytics (max 365) | 15 min | SEC-H4 |
| D4 | Limit `product_ids` in batch-fetch-images (max 20) | 15 min | SEC-H6 |
| D5 | Add replay protection to webhook (timestamp header) | 2h | SEC-H7 |
| D6 | Add role enforcement to remaining frontend pages | 4h | FE-H1 |
| D7 | Add React Error Boundaries (error.tsx per route) | 3h | FE-H3 |
| D8 | Fix all column type/width mismatches (6 models) | 2h | DB-H1, H2, H6-H10 |
| D9 | Add eager loading to content_service, publish_checker, engagement_puller | 2h | DB-H3-H5 |
| D10 | Add log rotation to remaining 10 Docker services | 1h | INFRA-H1 |
| D11 | Fix Valkey healthcheck (use REDISCLI_AUTH env var) | 15 min | INFRA-H2 |

### Phase E: AI/ML Updates (Week 3)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| E1 | Implement token tracking across all workflow nodes | 4h | AI-H3 |
| E2 | Add `rpm_limit`/`tpm_limit` to LiteLLM config | 2h | AI-H4 |
| E3 | Call `validate_llm_output()` in workflow nodes with retry | 4h | AI-H6 |
| E4 | Add model fallback chains to LiteLLM config | 1h | AI-L2 |
| E5 | Whitelist NATS payload fields per workflow type | 2h | AI-M3, AI-M4 |

### Phase F: Medium-Priority Fixes (Week 3-4)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| F1 | Restrict CORS methods/headers to explicit allowlist | 30 min | SEC-M2 |
| F2 | Add missing ondelete declarations to all FK models | 3h | DB-M2, DB-M3 |
| F3 | Generate Alembic baseline migration | 2h | DB-C2 |
| F4 | Implement Docker network segmentation | 4h | INFRA-M1 |
| F5 | Set up volume backup strategy (pg_dump, qdrant snapshot) | 4h | INFRA-M2 |
| F6 | Add reusable Pagination component + server-side pagination | 6h | FE-M1 |
| F7 | Adopt SWR or TanStack Query for data fetching | 8h | FE-M8 |
| F8 | Validate file uploads against magic bytes | 2h | SEC-M8 |
| F9 | Strip/block SVG uploads or sanitize embedded scripts | 2h | SEC-M9 |

### Phase G: Testing (Week 4-6)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| G1 | Set up pytest-cov; add CI coverage threshold (30% initial target) | 2h | PRE-009 |
| G2 | Write auth/RBAC integration tests | 8h | — |
| G3 | Write API endpoint tests for all 19 route modules (critical paths) | 16h | — |
| G4 | Set up Vitest + React Testing Library in frontend | 4h | FE-M3 |
| G5 | Write frontend auth flow and role enforcement tests | 8h | — |
| G6 | Add pre-commit hooks (ruff, eslint, .env blocking) | 2h | PRE-028 |

### Phase H: Infrastructure Hardening (Week 5-6)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| H1 | Add Docker build smoke test to CI | 2h | INFRA-M3 |
| H2 | Add pip-audit / npm audit to CI | 2h | INFRA-M3 |
| H3 | Deploy Alertmanager + configure Teams/email receivers | 4h | INFRA-L2 |
| H4 | Add missing Prometheus scrape targets | 2h | INFRA-M4 |
| H5 | Fix OTel Collector memory limiter to match container limit | 15 min | INFRA-L7 |
| H6 | Add HEALTHCHECK to remaining Dockerfiles | 1h | INFRA-H3 |
| H7 | Use docker-socket-proxy for Traefik | 2h | INFRA-H7 |

### Phase I: Low-Priority Polish (Week 6-8)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| I1 | Fix touch targets (min 44px on all interactive elements) | 4h | FE-L1 |
| I2 | Add ARIA labels/roles to calendar, Kanban, forms | 4h | FE-L3 |
| I3 | Consolidate duplicate frontend constants | 2h | FE-L4 |
| I4 | Replace custom DOM events with Zustand store for brand switching | 3h | FE-M2 |
| I5 | Add CPU limits to all containers | 1h | INFRA-L1 |
| I6 | Remove unused bcrypt dependency | 15 min | PRE-025 |
| I7 | Fix Grafana dashboard JSON reference | 30 min | INFRA-L6 |

### Phase J: Major Version Upgrades (Week 8-12)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| J1 | Migrate next-auth v4 → Auth.js v5 | 8h | DEP-H7 |
| J2 | Upgrade TypeScript 5 → 6 | 4h | DEP-H4 |
| J3 | Upgrade ESLint 9 → 10 | 4h | DEP-H5 |
| J4 | Upgrade n8n 1.x → 2.x | 8h | DEP-H6 |
| J5 | Evaluate PostgreSQL 16 → 17 upgrade | 4h | — |

### Phase K: Documentation & Process (Ongoing)

| # | Action | Effort | Finding |
|---|--------|--------|---------|
| K1 | Document all intentional public endpoints with justification | 2h | — |
| K2 | Create runbook for secret rotation | 4h | SEC-C1 |
| K3 | Document backup and disaster recovery procedure | 4h | INFRA-M2 |
| K4 | Add soft-delete pattern for critical entities | 8h | PRE-026 |

---

## 11. METRICS DASHBOARD

| Metric | Value |
|--------|-------|
| **Total files audited** | ~200+ (across all services) |
| **Total findings** | **142** |
| **Critical** | 16 |
| **High** | 37 |
| **Medium** | 39 |
| **Low** | 38 |
| **Info/Positive** | 12 |
| **Pre-loaded issues confirmed** | 30/30 (100%) |
| **New issues discovered** | 112 |
| **CVEs found** | 5 (LiteLLM CVSS 9.4, Traefik ×2, PyJWT, Next.js ×2) |
| **Dependencies audited** | 61 |
| **Dependencies current** | 42 (69%) |
| **Dependencies with known CVEs** | 4 (7%) |
| **Major version behind** | 5 (8%) |
| **Test coverage** | ~1-2% |
| **Frontend test coverage** | 0% |
| **Pages with role enforcement** | 4/21 (19%) |
| **Services with log rotation** | 3/13 (23%) |
| **Services with healthchecks** | 9/15 (60%) |
| **SQL injection vulnerabilities** | 0 (all parameterized) |
| **N+1 query patterns** | 3 confirmed |
| **Schema/model mismatches** | 8 |

---

*Report generated 2026-04-02 by automated multi-agent codebase audit.*
*Audit methodology: 6 parallel specialized agents (security, dependencies, AI/ML, database, frontend, infrastructure) with web-verified dependency checks.*
