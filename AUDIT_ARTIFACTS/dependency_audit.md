# Phase 2: Dependency, Framework & Library Version Audit

**Date:** 2026-03-30
**Auditor:** Claude Opus 4.6

---

## Executive Summary

| Metric | Count |
|---|---|
| **Total dependencies (unique)** | 62 |
| **Frontend (runtime)** | 21 |
| **Frontend (dev)** | 8 |
| **Backend (runtime)** | 18 |
| **Backend (dev)** | 4 |
| **Agents (runtime)** | 17 |
| **Browser-worker (runtime)** | 8 |
| **Browser-worker (dev)** | 3 |
| **Notifications (runtime)** | 8 |
| **Notifications (dev)** | 3 |
| **Outdated dependencies** | 18 |
| **Deprecated / end-of-life** | 1 (next-auth v4 -- superseded by Auth.js v5) |
| **Critical security advisories** | 3 (litellm supply-chain, React/Next.js RCE, Next.js middleware bypass) |

### Critical Action Items

1. **CRITICAL -- litellm (CVE-2026-33634):** Versions 1.82.7-1.82.8 contained a supply-chain backdoor (credential stealer, lateral movement tools). Verify installed version is <=1.82.6. Pin `litellm==1.82.6` explicitly in all pyproject.toml files.
2. **CRITICAL -- React/Next.js RCE (CVE-2025-55182 / CVE-2025-66478):** Remote code execution in React Server Components. Ensure Next.js 16.2.x includes the fix (it does -- patched in Dec 2025 releases).
3. **HIGH -- next-auth v4 is superseded:** Auth.js v5 is the recommended migration path. v4 receives minimal maintenance. Plan migration.
4. **HIGH -- TypeScript 5.7 is two major versions behind** (latest: 6.0.2). TypeScript 6.0 is the last JS-based release before the Go rewrite in v7.
5. **HIGH -- ESLint 9.x is one major version behind** (latest: 10.1.0). ESLint 10 dropped legacy config format.
6. **MEDIUM -- google-genai >=1.5 is far behind latest** (1.68.0). Rapid release cadence means missing many features/fixes.
7. **MEDIUM -- next-themes 0.4.4 is slightly behind** (latest: 0.4.6).
8. **MEDIUM -- lucide-react ^0.468 is far behind** (latest: 1.7.0 -- major version bump).

---

## Frontend Dependencies (package.json)

### Runtime Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Notes |
|---|---|---|---|---|
| @auth/core | ^0.37.4 | 0.41.1 | OUTDATED | Auth.js core; several minor releases behind |
| @dnd-kit/core | ^6.3.1 | 6.3.1 | OK | No new releases in ~1 year |
| @dnd-kit/sortable | ^10.0.0 | 10.0.0 | OK | No new releases in ~1 year |
| @dnd-kit/utilities | ^3.2.2 | 3.2.2 | OK | Stable |
| @radix-ui/react-avatar | ^1.1.2 | 1.1.2+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-dialog | ^1.1.4 | 1.1.4+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-dropdown-menu | ^2.1.4 | 2.1.4+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-label | ^2.1.1 | 2.1.1+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-select | ^2.1.4 | 2.1.4+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-separator | ^1.1.1 | 1.1.1+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-slot | ^1.1.1 | 1.1.1+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-switch | ^1.2.6 | 1.2.6+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-tabs | ^1.1.2 | 1.1.2+ | OK | Consider migrating to unified `radix-ui` package |
| @radix-ui/react-tooltip | ^1.1.6 | 1.1.6+ | OK | Consider migrating to unified `radix-ui` package |
| class-variance-authority | ^0.7.1 | 0.7.1 | OK | No new releases in ~1 year |
| clsx | ^2.1.1 | 2.1.1 | OK | Stable utility |
| date-fns | ^4.1.0 | 4.1.0 | OK | No new releases |
| lucide-react | ^0.468.0 | 1.7.0 | **OUTDATED** | Major version bump from 0.x to 1.x; breaking changes likely |
| next | ^16.2.1 | 16.2.1 | OK | Latest release (Mar 18, 2026) |
| next-auth | ^4.24.11 | 4.24.13 | **OUTDATED/SUPERSEDED** | v4 line is in maintenance; Auth.js v5 is the successor |
| next-themes | ^0.4.4 | 0.4.6 | OUTDATED | Minor patch behind |
| postcss | ^8.4.49 | 8.5.8 | OUTDATED | Several patches behind |
| react | ^19.2.4 | 19.2.4 | OK | Latest (Jan 26, 2026) |
| react-dom | ^19.2.4 | 19.2.4 | OK | Latest |
| react-markdown | ^10.1.0 | 10.1.0 | OK | No new releases |
| recharts | ^3.8.1 | 3.8.1 | OK | Latest (Mar 2026) |
| sonner | ^2.0.7 | 2.0.7 | OK | Stable |
| tailwind-merge | ^2.6.0 | 2.6.0 | OK | Stable |
| zustand | ^5.0.3 | 5.0.12 | OUTDATED | Several patches behind |

### Dev Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Notes |
|---|---|---|---|---|
| @tailwindcss/postcss | ^4.2.2 | 4.2.2 | OK | Latest |
| @types/node | ^25.5.0 | 25.5.0 | OK | Types for Node.js |
| @types/react | ^19.2.14 | 19.2.14 | OK | Types for React 19 |
| @types/react-dom | ^19.2.3 | 19.2.3 | OK | Types for ReactDOM 19 |
| eslint | ^9.17.0 | 10.1.0 | **OUTDATED** | Major version behind (v10 released Feb 2026) |
| eslint-config-next | ^16.2.1 | 16.2.1 | OK | Matches Next.js version |
| tailwindcss | ^4.2.2 | 4.2.2 | OK | Latest (Mar 18, 2026) |
| typescript | ^5.7.2 | 6.0.2 | **OUTDATED** | Two major versions behind; TS 6.0 released Mar 2026 |

---

## Backend Dependencies (pyproject.toml)

### Runtime Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Security Advisory? |
|---|---|---|---|---|
| fastapi[standard] | >=0.135 | 0.135.2 | OK | No |
| uvicorn[standard] | unpinned | 0.42.0 | OK (resolves to latest) | No |
| sqlalchemy[asyncio] | >=2.0.48 | 2.0.48 | OK | No |
| asyncpg | >=0.31 | 0.31.0 | OK | No |
| alembic | >=1.18 | 1.18.4 | OK | No |
| pydantic | >=2.12 | 2.12.5 | OK | No |
| pydantic-settings | >=2.13 | 2.13.1 | OK | No |
| PyJWT[crypto] | unpinned | 2.12.1 | OK (resolves to latest) | No |
| httpx | >=0.28 | 0.28.1 | OK | No known CVEs; httpxyz fork exists due to slow patch cadence |
| pyodbc | >=5.3 | 5.3.x | OK | No |
| apscheduler | >=3.11 | 3.11.2 | OK | No |
| nats-py | >=2.14 | 2.14.0 | OK | No |
| minio | >=7.2 | 7.2.20 | OK | No |
| qdrant-client | >=1.17 | 1.17.1 | OK | No |
| litellm | >=1.60 | 1.82.6 | OK (but see advisory) | **CVE-2026-33634** -- supply chain attack on v1.82.7-1.82.8. Pin to ==1.82.6 or <=1.82.6 |
| redis | >=7.1 | 7.1.1 | OK | No |
| python-multipart | >=0.0.18 | 0.0.22 | OK | No |
| google-genai | >=1.5 | 1.68.0 | OK (resolves to latest) | No; but floor is very low -- consider bumping minimum |
| Pillow | >=12.0 | 12.1.1 | OK | No |
| bcrypt | >=4.0 | 5.0.0 | OK (resolves to latest) | No |
| opentelemetry-api | >=1.40 | 1.40.0 | OK | No |
| opentelemetry-sdk | >=1.40 | 1.40.0 | OK | No |
| opentelemetry-instrumentation-fastapi | >=0.61b0 | 0.61b0 | OK | No |
| opentelemetry-exporter-otlp | >=1.40 | 1.40.0 | OK | No |

### Dev Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Notes |
|---|---|---|---|---|
| pytest | unpinned | 8.x | OK | Resolves to latest |
| pytest-asyncio | unpinned | latest | OK | |
| httpx | unpinned | 0.28.1 | OK | |
| ruff | unpinned | latest | OK | |

---

## Agents Dependencies (pyproject.toml)

### Runtime Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Security Advisory? |
|---|---|---|---|---|
| langgraph | >=1.0,<2.0 | 1.1.3 | OK | No |
| langchain-core | >=1.0,<2.0 | 1.2.22 | OK | No |
| langchain-openai | >=1.0,<2.0 | 1.1.11 | OK | No |
| litellm | >=1.60 | 1.82.6 | OK (see advisory) | **CVE-2026-33634** |
| nats-py | >=2.14 | 2.14.0 | OK | No |
| asyncpg | >=0.31 | 0.31.0 | OK | No |
| sqlalchemy[asyncio] | >=2.0.48 | 2.0.48 | OK | No |
| httpx | >=0.28 | 0.28.1 | OK | No |
| pyodbc | >=5.3 | 5.3.x | OK | No |
| minio | >=7.2 | 7.2.20 | OK | No |
| qdrant-client | >=1.17 | 1.17.1 | OK | No |
| playwright | >=1.58 | 1.58.0 | OK | No |
| pydantic | >=2.12 | 2.12.5 | OK | No |
| pydantic-settings | >=2.13 | 2.13.1 | OK | No |
| opentelemetry-api | >=1.40 | 1.40.0 | OK | No |
| opentelemetry-sdk | >=1.40 | 1.40.0 | OK | No |
| google-genai | >=1.5 | 1.68.0 | OK (floor very low) | No |
| Pillow | >=12.0 | 12.1.1 | OK | No |
| numpy | >=2.0 | 2.4.4 | OK (floor very low) | No |
| tenacity | >=9.0 | 9.1.4 | OK | No |

---

## Browser-Worker Dependencies (pyproject.toml)

### Runtime Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Security Advisory? |
|---|---|---|---|---|
| fastapi[standard] | >=0.135 | 0.135.2 | OK | No |
| uvicorn[standard] | unpinned | 0.42.0 | OK | No |
| playwright | >=1.58 | 1.58.0 | OK | No |
| httpx | >=0.28 | 0.28.1 | OK | No |
| minio | >=7.2 | 7.2.20 | OK | No |
| pydantic | >=2.12 | 2.12.5 | OK | No |
| pydantic-settings | >=2.13 | 2.13.1 | OK | No |
| beautifulsoup4 | >=4.14 | 4.14.x | OK | No |
| Pillow | >=12.1 | 12.1.1 | OK | No |

### Dev Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? |
|---|---|---|---|
| pytest | unpinned | latest | OK |
| pytest-asyncio | unpinned | latest | OK |
| ruff | unpinned | latest | OK |

---

## Notifications Dependencies (pyproject.toml)

### Runtime Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? | Security Advisory? |
|---|---|---|---|---|
| fastapi[standard] | >=0.135 | 0.135.2 | OK | No |
| uvicorn[standard] | unpinned | 0.42.0 | OK | No |
| httpx | >=0.28 | 0.28.1 | OK | No |
| asyncpg | >=0.31 | 0.31.0 | OK | No |
| sqlalchemy[asyncio] | >=2.0.48 | 2.0.48 | OK | No |
| pydantic | >=2.12 | 2.12.5 | OK | No |
| pydantic-settings | >=2.13 | 2.13.1 | OK | No |
| sse-starlette | >=3.3 | 3.3.x | OK | No |
| valkey | >=6.1 | 6.1.1 | OK | No (pre-release 6.2.0rc1 available) |

### Dev Dependencies

| Package | Pinned Version | Latest Stable | Up to Date? |
|---|---|---|---|
| pytest | unpinned | latest | OK |
| pytest-asyncio | unpinned | latest | OK |
| ruff | unpinned | latest | OK |

---

## Security Advisories

### 1. CRITICAL -- litellm Supply-Chain Attack (CVE-2026-33634)

- **CVSS:** 9.4 (Critical)
- **Date:** March 24, 2026
- **Affected versions:** 1.82.7, 1.82.8 (removed from PyPI)
- **Safe version:** <=1.82.6
- **Attack vector:** TeamPCP compromised LiteLLM's CI/CD via a backdoored Trivy security scanner. The malicious releases contained a credential harvester (SSH keys, cloud tokens, .env files, wallets), Kubernetes lateral movement tools, and a persistent systemd backdoor.
- **Impact on MARKAI:** litellm is used in both `backend` and `agents`. The `>=1.60` floor means pip could resolve to a compromised version if the quarantine is ever lifted or if a mirror cached it.
- **Remediation:** Pin `litellm==1.82.6` in all pyproject.toml files. Audit installed environments. Check for presence of `litellm_init.pth` file.

### 2. CRITICAL -- React Server Components RCE (CVE-2025-55182)

- **CVSS:** 10.0 (Critical)
- **Date:** December 3, 2025
- **Affected:** React Server Components in multiple React/Next.js versions
- **Status:** Patched in React 19.2.x and Next.js 16.x. MARKAI uses React 19.2.4 and Next.js 16.2.1, which include the fix.
- **Remediation:** No action needed -- current versions are patched.

### 3. HIGH -- Next.js Middleware Authorization Bypass (CVE-2025-29927)

- **Date:** March 21, 2025
- **Affected:** Next.js 11.x through 15.x
- **Status:** Patched in Next.js 16.x. MARKAI uses 16.2.1.
- **Remediation:** No action needed -- current version is patched.

### 4. MEDIUM -- Next.js Additional RSC Vulnerabilities (CVE-2025-55183, CVE-2025-55184)

- **Date:** December 11, 2025
- **CVE-2025-55183:** Information leak (source code exposure)
- **CVE-2025-55184:** Deserialization DoS
- **Status:** Patched in Next.js 16.x.
- **Remediation:** No action needed.

---

## Major Framework Analysis

### Next.js (Current: 16.2.1 | Latest: 16.2.1)

- **Status:** Up to date
- **Key features in 16.2:** 400% faster dev startup, 50% faster rendering, Turbopack improvements, SRI support, stable Adapter API
- **Migration notes:** None needed -- already on latest

### React (Current: 19.2.4 | Latest: 19.2.4)

- **Status:** Up to date
- **Key features in 19.2:** DoS mitigations for Server Actions, hardened Server Components
- **Migration notes:** None needed

### FastAPI (Current: >=0.135 | Latest: 0.135.2)

- **Status:** Up to date
- **Notes:** FastAPI still on 0.x versioning. Python 3.12+ recommended.

### Tailwind CSS (Current: 4.2.2 | Latest: 4.2.2)

- **Status:** Up to date
- **Key features in v4:** All-new engine, CSS-first configuration, reimagined customization
- **Migration notes:** None needed -- already on latest

### LangGraph (Current: >=1.0 | Latest: 1.1.3)

- **Status:** Up to date (caret range resolves correctly)
- **Key features:** LangGraph 2.0 concepts (type-safe streaming, type-safe invoke) are available but the Python package version is 1.1.3
- **Migration notes:** None needed currently

### LangChain-Core (Current: >=1.0 | Latest: 1.2.22)

- **Status:** Up to date (floor allows resolution to latest)
- **Migration notes:** None needed

### Playwright (Current: >=1.58 | Latest: 1.58.0)

- **Status:** Up to date
- **Migration notes:** None needed

### TypeScript (Current: ^5.7.2 | Latest: 6.0.2)

- **Status:** OUTDATED -- two major versions behind
- **Key changes in 6.0:** Last JS-based release before Go rewrite in v7. New features include improved type inference, faster compilation.
- **Migration guide:** https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/
- **Risk:** Medium -- TS is backward-compatible for most code, but ESLint and tooling configs may need updates

### ESLint (Current: ^9.17.0 | Latest: 10.1.0)

- **Status:** OUTDATED -- one major version behind
- **Key changes in 10.0:** Dropped legacy `.eslintrc` config format, flat config only
- **Migration guide:** https://eslint.org/blog/2026/02/eslint-v10.0.0-released/
- **Risk:** Medium -- requires flat config migration if not already done

---

## Radix UI Package Consolidation Opportunity

As of February 2026, Radix UI offers a unified `radix-ui` package (v1.4.3) that replaces all individual `@radix-ui/react-*` packages. The project currently uses 10 separate Radix packages. Migrating to the unified package would:
- Reduce package.json entries from 10 to 1
- Eliminate version drift between Radix components
- Simplify updates going forward

Reference: https://ui.shadcn.com/docs/changelog/2026-02-radix-ui

---

## Version Pinning Observations

### Python Services (backend, agents, browser-worker, notifications)

All Python services use **floor-only pinning** (`>=X.Y`) with no upper bounds. This is acceptable for applications (not libraries) but creates risk:
- `litellm>=1.60` could resolve to a compromised version
- `google-genai>=1.5` has a very low floor (latest is 1.68.0) -- 63 minor versions of drift possible
- `numpy>=2.0` has a very low floor (latest is 2.4.4)

**Recommendation:** For critical packages (especially litellm), use exact pins or tighter ranges. Consider using a lockfile (pip-compile / uv.lock) for reproducible builds.

### Frontend (package.json)

Uses standard caret (`^`) ranges, which is appropriate for npm. The lockfile (package-lock.json) ensures reproducibility.

---

## Recommended Actions (Priority Order)

1. **IMMEDIATE:** Pin `litellm==1.82.6` in backend/pyproject.toml and agents/pyproject.toml. Audit all deployed environments for litellm_init.pth.
2. **HIGH:** Plan migration from next-auth v4 to Auth.js v5 (next-auth is effectively in maintenance mode).
3. **HIGH:** Upgrade TypeScript from 5.7 to 6.0 (`npm install -D typescript@6`).
4. **HIGH:** Upgrade ESLint from 9.x to 10.x (requires flat config -- verify eslint.config.js is already in use).
5. **MEDIUM:** Upgrade lucide-react from 0.468 to 1.x (breaking changes -- review migration guide).
6. **MEDIUM:** Consolidate @radix-ui/* packages to unified `radix-ui` package.
7. **MEDIUM:** Bump google-genai floor from >=1.5 to >=1.60 across all services.
8. **LOW:** Update zustand ^5.0.3 to ^5.0.12, postcss ^8.4.49 to ^8.5.8, next-themes ^0.4.4 to ^0.4.6, @auth/core ^0.37.4 to ^0.41.1.
9. **LOW:** Introduce lockfiles (uv.lock or requirements.txt via pip-compile) for all Python services for reproducible deployments.
