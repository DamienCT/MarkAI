# MARKAI Technology Stack Research Report

**Date:** March 24, 2026
**Purpose:** Audit all technologies used in the MARKAI project against current latest stable versions and best practices.

---

## Executive Summary

Several technologies in the MARKAI stack are significantly behind current stable releases. The most impactful upgrades are:

1. **Next.js 15 -> 16.2** (breaking changes, medium effort)
2. **LangGraph 0.4 -> 1.1.0** (major stable release, high effort)
3. **MinIO is archived** (critical -- needs replacement planning)
4. **Valkey 8 -> 9.0.3** (performance gains, low-medium effort)
5. **Python 3.12 -> 3.14** (recommended, medium effort)
6. **Recharts 2.x -> 3.8** (breaking changes, medium effort)
7. **OpenAI models** (GPT-4o deprecated in ChatGPT, GPT-4.1/5.4 available)

---

## 1. Next.js

| Attribute | Value |
|---|---|
| **Project uses** | ^15.1.0 |
| **Latest stable** | 16.2.0 (March 18, 2026) |
| **Recommended action** | Upgrade |
| **Migration effort** | **Medium-High** |

### Key Changes Since 15.x
- **Turbopack is now the default bundler** -- custom Webpack configs are ignored under Turbopack
- **Async Request APIs only** -- synchronous access to `cookies`, `headers`, `params`, `searchParams` fully removed
- **Middleware -> Proxy migration** -- `middleware.ts` replaced by `proxy.ts` for routing logic
- **AMP support fully removed**
- **Partial Prerendering** -- `experimental_ppr` flag removed, replaced with `cacheComponents`
- **next/image** -- `objectFit`, `objectPosition`, `layout` props deprecated in favor of CSS
- **~400% faster** `next dev` startup, ~50% faster rendering
- **Turbopack File System Caching** for `next dev` (stable)
- **Adapters** are now stable for platform customization

### Breaking Changes
- All request APIs must be awaited (async only)
- Custom Webpack configuration ignored when Turbopack enabled
- AMP pages must be migrated
- Middleware.ts -> proxy.ts migration needed

### Recommendation
Upgrade to 16.2.x. Use the automated codemod: `npx @next/codemod@canary upgrade latest`. Audit all middleware logic and async API usage first.

---

## 2. FastAPI

| Attribute | Value |
|---|---|
| **Project uses** | >=0.115 |
| **Latest stable** | 0.135.1 (March 1, 2026) |
| **Recommended action** | Upgrade |
| **Migration effort** | **Low** |

### Key Changes
- Continued incremental releases with no major breaking changes
- Pydantic v2 integration is mature and stable
- Improved async patterns and middleware support
- HTTP/3 support available via uvicorn configuration

### Recommendation
Bump version constraint to `>=0.135`. FastAPI follows semver-compatible releases; this should be a drop-in upgrade.

---

## 3. LangGraph

| Attribute | Value |
|---|---|
| **Project uses** | >=0.4 |
| **Latest stable** | 1.1.0 (March 10, 2026) |
| **Recommended action** | **Upgrade (priority)** |
| **Migration effort** | **High** |

### Key Changes Since 0.4
- **LangGraph 1.0 GA** -- first stable major release, used in production by Uber, LinkedIn, Klarna
- **Type-safe streaming** (`version="v2"`) -- unified `StreamPart` output with type, ns, data keys
- **Type-safe invoke** (`version="v2"`) -- `GraphOutput` object with `.value` and `.interrupts`
- **Pydantic/dataclass coercion** -- output automatically coerced to declared types
- **Fixed time travel with interrupts and subgraphs**
- **Chat model `.profile` attribute** -- exposes supported features/capabilities
- **Retry middleware** -- configurable exponential backoff for model calls
- **Content moderation middleware** for OpenAI

### Breaking Changes
- Major version bump from 0.x to 1.x -- API surface changes
- `langchain-core>=0.3` still compatible but check for deprecations
- `version="v2"` is opt-in and backwards compatible

### Recommendation
This is a critical upgrade. LangGraph 1.0+ is the production-ready release. Plan a dedicated sprint to migrate from 0.4 to 1.1.0. The type-safe APIs and improved interrupt handling are significant improvements for the agent workflows.

---

## 4. LiteLLM

| Attribute | Value |
|---|---|
| **Project uses** | latest (unpinned) |
| **Latest stable** | 1.82.4 (March 22, 2026) |
| **Recommended action** | Pin version |
| **Migration effort** | **Low** |

### Key Changes
- Supports 100+ LLM provider APIs
- Routing strategies: simple-shuffle, least-busy, usage-based, latency-based
- Model group aliases and retry settings
- Docker deployment at port 4000 with config.yaml mount (already configured correctly)

### Recommendation
Pin to a specific version (`litellm>=1.82`) in pyproject.toml. The unpinned dependency is a stability risk. The Docker image `ghcr.io/berriai/litellm:main-latest` should be pinned to a specific tag.

---

## 5. PostgreSQL 16

| Attribute | Value |
|---|---|
| **Project uses** | postgres:16-alpine |
| **Latest stable** | 16.13 (February 26, 2026) |
| **Recommended action** | Update image tag |
| **Migration effort** | **Low** |

### Key Changes
- 16.13 is an out-of-cycle release fixing regressions from previous patches
- Security and bug fixes only -- no feature changes
- Note: PostgreSQL 18.2 and 17.8 are also available if considering a major version upgrade

### Recommendation
Pin to `postgres:16.13-alpine` for reproducibility. The current `16-alpine` tag will auto-update but in an unpredictable manner.

---

## 6. Qdrant

| Attribute | Value |
|---|---|
| **Project uses** | qdrant/qdrant:latest |
| **Latest stable** | 1.17.0 (February 19, 2026) |
| **Python client** | 1.17.1 (March 13, 2026) |
| **Recommended action** | Pin version |
| **Migration effort** | **Low** |

### Key Changes
- **v1.17.0**: Changed gRPC response format for vector fields; RocksDB completely removed in favor of gridstore
- **Relevance feedback queries** for improved recall
- **Delayed fan-out** for multi-replica latency optimization
- **Cluster-wide telemetry API**
- 4-bit quantization and tiered multitenancy on roadmap

### Breaking Changes
- gRPC vector field response format changed in 1.17.0
- RocksDB storage removed -- gridstore only

### Recommendation
Pin to `qdrant/qdrant:v1.17.0`. If using gRPC directly, test for response format changes. Update `qdrant-client` in pyproject.toml to `>=1.17`.

---

## 7. NATS JetStream

| Attribute | Value |
|---|---|
| **Project uses** | nats:latest |
| **Latest stable** | 2.12.5 (March 9, 2026) |
| **Recommended action** | Pin version (with caution) |
| **Migration effort** | **Low** |

### Key Changes
- Stream snapshot/backup accepts `window_size` parameter for flow control
- **Warning**: v2.12.5 has a known regression where stream updates may lose consumers in clustered deployments

### Recommendation
Pin to `nats:2.12.4` until the consumer loss regression in 2.12.5 is resolved. For single-server deployments (like dev), 2.12.5 is safe.

---

## 8. MinIO

| Attribute | Value |
|---|---|
| **Project uses** | minio/minio:latest |
| **Latest stable** | RELEASE.2025-10-15 (archived) |
| **Python SDK** | 7.2.20 |
| **Recommended action** | **Plan replacement** |
| **Migration effort** | **High** |

### CRITICAL: MinIO Repository Archived

As of February 13, 2026, the MinIO community repository has been archived and is in maintenance mode:
- No new features or enhancements
- No pull requests accepted
- Critical security fixes evaluated case-by-case only
- Docker images pulled from Docker Hub and Quay
- Pre-compiled binary releases discontinued (since October 2025)

### Alternatives
| Alternative | License | Notes |
|---|---|---|
| **RustFS** | Apache 2.0 | S3-compatible, supports MinIO migration/coexistence, 2.3x faster for small objects |
| **Garage** | AGPL-3.0 | Lightweight, designed for self-hosting |
| **Ceph** | LGPL | Most mature, but heavier operational overhead |
| **Apache Ozone** | Apache 2.0 | Foundation-owned (ASF), avoids licensing risk |

### Recommendation
**This is the highest-priority action item.** The MinIO Docker image may stop receiving security patches. Short-term: pin to last known good image. Medium-term: evaluate RustFS or Garage as S3-compatible drop-in replacements. The Python `minio` SDK should continue to work with any S3-compatible backend.

---

## 9. Valkey

| Attribute | Value |
|---|---|
| **Project uses** | valkey/valkey:8-alpine |
| **Latest stable** | 9.0.3 (February 23, 2026) |
| **Recommended action** | Upgrade |
| **Migration effort** | **Low-Medium** |

### Key Changes in 9.0
- Multi-database support in cluster mode
- Atomic slot migration
- Official modules for JSON, Bloom filters, and search
- Over 1 billion requests/second on 2,000-node clusters
- Security fixes in 9.0.3 (RESP injection, DoS vulnerabilities)

### API Compatibility
- Fully compatible with Redis 7.2 protocol
- The project's `redis>=5.0` Python dependency works with Valkey (same protocol)
- Multi-threaded performance optimizations

### Recommendation
Upgrade to `valkey/valkey:9-alpine`. The Python `redis` package works unchanged. Consider renaming the dependency to `valkey` package if one exists, for clarity.

---

## 10. Traefik v3

| Attribute | Value |
|---|---|
| **Project uses** | traefik:v3.2 |
| **Latest stable** | 3.6.11 (March 19, 2026) |
| **Recommended action** | Upgrade |
| **Migration effort** | **Low** |

### Key Changes Since 3.2
- Security fixes (multiple CVEs)
- Gateway API v1.5.1 support
- Knative v1.20.0 support
- Only the last minor release receives bug and security fixes

### Recommendation
Upgrade to `traefik:v3.6` in docker-compose.yml. The v3.2 image is no longer receiving security patches. This is a straightforward image tag update with no config changes expected.

---

## 11. NextAuth.js / Auth.js

| Attribute | Value |
|---|---|
| **Project uses** | next-auth ^4.24.11, @auth/core ^0.37.4 |
| **Latest v4** | 4.24.13 |
| **v5 status** | Beta (but production-ready, maintained by Better Auth team) |
| **Recommended action** | Migrate to v5 |
| **Migration effort** | **Medium** |

### Key Changes in v5
- Universal `auth()` method replaces `getServerSession`, `getSession`, `withAuth`, `getToken`, `useSession`
- App Router-first design
- OAuth 1.0 support dropped
- Minimum Next.js 14.0 required
- Database schema largely backward compatible

### Note on Governance
Auth.js (formerly NextAuth.js) is now maintained by the Better Auth team. v4 is effectively in maintenance-only mode.

### Recommendation
When upgrading to Next.js 16, migrate to Auth.js v5 simultaneously. Install via `npm install next-auth@beta`. The unified `auth()` API simplifies server-side auth significantly.

---

## 12. Playwright

| Attribute | Value |
|---|---|
| **Project uses** | unpinned (`playwright`) |
| **Latest stable** | 1.58.2 (January 2026) |
| **Recommended action** | Pin version |
| **Migration effort** | **Low** |

### Key Changes
- Switched from Chromium to Chrome for Testing
- Timeline in HTML report (Speedboard tab)
- IndexedDB support in `storageState()`
- `_react` and `_vue` selectors removed
- Chrome extension Manifest V2 no longer supported
- `devtools` option removed from `browserType.launch()`

### Recommendation
Pin to `playwright>=1.58` in pyproject.toml. If using `_react` or `_vue` selectors, migrate to modern alternatives.

---

## 13. APScheduler

| Attribute | Value |
|---|---|
| **Project uses** | >=3.10 |
| **Latest stable (v3)** | 3.11.2 |
| **v4 status** | Pre-release (NOT production ready) |
| **Recommended action** | Update to 3.11.x, stay on v3 |
| **Migration effort** | **Low** |

### Key Notes
- v4.0 is a ground-up async-first redesign but is explicitly labeled "do NOT use in production"
- v3.x `AsyncIOScheduler` works well for async FastAPI applications
- v3.11.2 is stable and maintained

### Recommendation
Bump to `apscheduler>=3.11,<4.0` to get latest fixes while blocking unstable v4. Monitor v4 progress for future migration.

---

## 14. OpenTelemetry Python SDK

| Attribute | Value |
|---|---|
| **Project uses** | unpinned |
| **Latest stable** | 1.40.0 (March 4, 2026) |
| **Recommended action** | Pin version |
| **Migration effort** | **Low** |

### Key Notes
- `opentelemetry-instrumentation-fastapi` provides automatic instrumentation
- Single-line `FastAPIInstrumentor.instrument_app(app)` captures all HTTP requests
- Supports Python 3.9+

### Recommendation
Pin versions: `opentelemetry-api>=1.40`, `opentelemetry-sdk>=1.40`. The current setup pattern is correct.

---

## 15. Grafana / Prometheus / Loki

| Component | Project Uses | Latest Stable |
|---|---|---|
| **Grafana** | grafana/grafana:latest | 12.4.1 (March 2026) |
| **Prometheus** | prom/prometheus:latest | 3.10.0 (February 24, 2026) |
| **Loki** | grafana/loki:latest | 3.6.7 (February 2026) |

### Key Changes
- **Grafana 12.x**: Major version jump from 11.x series
- **Prometheus 3.x**: Distroless Docker image variant for security
- **Loki**: Promtail is **deprecated** (commercial support ended February 28, 2026) -- migrate to **Grafana Alloy**

### Breaking Changes
- If using Promtail for log collection, must migrate to Grafana Alloy

### Recommendation
Pin all images to specific versions. Replace Promtail with Grafana Alloy if used. Migration effort: **Low** for version pinning, **Medium** if Promtail migration needed.

---

## 16. shadcn/ui

| Attribute | Value |
|---|---|
| **Project uses** | Individual @radix-ui/react-* packages |
| **Latest** | CLI v4 (March 2026) |
| **Recommended action** | Migrate to unified radix-ui package |
| **Migration effort** | **Medium** |

### Key Changes (2026)
- **Unified `radix-ui` package** replaces individual `@radix-ui/react-*` packages (February 2026)
- **CLI v4** with AI agent skills, design system presets, `--dry-run`, `--diff`, `--view` flags
- **registry:base** for distributing entire design systems as single payload
- **Inline start/end styles** support

### Recommendation
Replace individual `@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu`, etc. with the unified `radix-ui` package for cleaner dependency management. Use `shadcn init` for scaffolding.

---

## 17. Recharts

| Attribute | Value |
|---|---|
| **Project uses** | ^2.15.0 |
| **Latest stable** | 3.8.0 (March 6, 2026) |
| **Recommended action** | Upgrade |
| **Migration effort** | **Medium** |

### Breaking Changes in 3.0
- Internal state management completely rewritten
- `recharts-scale` and `react-smooth` dependencies removed (internalized)
- `CategoricalChartState` removed
- `activeIndex` prop removed
- `accessibilityLayer` now `true` by default
- Z-index determined by render order (SVG behavior)
- `blendStroke` prop removed from Pie (use `stroke="none"`)
- `alwaysShow` and `isFront` props removed from reference elements

### Recommendation
Follow the [3.0 migration guide](https://github.com/recharts/recharts/wiki/3.0-migration-guide). Test all chart components after upgrade. The state management rewrite may affect custom chart interactions.

---

## 18. OpenAI API

| Attribute | Value |
|---|---|
| **Project likely uses** | GPT-4o models |
| **Latest flagship** | GPT-5.4 (March 5, 2026) |
| **Latest efficient** | GPT-4.1, GPT-4.1 mini, GPT-4.1 nano |
| **Image generation** | gpt-image-1.5, chatgpt-image-latest |
| **Recommended action** | Update model references |
| **Migration effort** | **Low-Medium** |

### Key Changes
- **GPT-4o deprecated** in ChatGPT (February 13, 2026) -- still available in API but signals end-of-life
- **GPT-4.1 family** outperforms GPT-4o across the board (coding, instruction following)
- **GPT-5.4** variants: standard, Thinking (reasoning), Pro (high performance)
- **GPT-5.4-mini and GPT-5.4-nano** for lower-cost workloads
- **gpt-image-1.5** for image generation (not gpt-image-1)

### Recommendation
Update LiteLLM config to use GPT-4.1 as the default model (best price/performance for most tasks). Add GPT-5.4 as an option for complex reasoning. Update image generation references to `gpt-image-1.5`.

---

## 19. Microsoft Fabric REST API

| Attribute | Value |
|---|---|
| **Recommended action** | Adopt new capabilities |
| **Migration effort** | **Low** |

### Key Changes (January-March 2026)
- **Python SDK** for Fabric REST API (preview, January 2026)
- **Notebook Job Scheduler API** with parameterized runs and exit values (March 2026)
- **Workload Management Admin APIs** for tenant governance (March 2026)
- **Tenant Settings API** for programmatic management (February 2026)
- **ODBC Driver** for Spark SQL connectivity with Lakehouse (February 2026)
- **High Concurrency mode** for Lakehouse operations (January 2026)

### Recommendation
Evaluate the Python SDK preview for replacing raw REST calls. The notebook execution API with exit values enables richer orchestration patterns.

---

## 20. Docker Compose

| Attribute | Value |
|---|---|
| **Project uses** | `version: "3.9"` |
| **Latest** | Compose Specification (no version key) |
| **Recommended action** | Remove version key, rename file |
| **Migration effort** | **Low** |

### Key Changes
- The `version` key is **deprecated and ignored** -- remove it from docker-compose.yml
- Preferred filename is `compose.yaml` (not `docker-compose.yml`)
- Compose v2 CLI plugin is the standard
- Legacy format versions 2.x/3.x merged into unified Compose Specification

### Recommendation
Remove `version: "3.9"` from docker-compose.yml. Optionally rename to `compose.yaml`. Pin all `:latest` image tags to specific versions for reproducibility.

---

## Runtime Environments

### Python

| Attribute | Value |
|---|---|
| **Project uses** | 3.12 |
| **Latest stable** | 3.14.3 (February 3, 2026) |
| **Recommended** | 3.14.x for new deployments |
| **Migration effort** | **Medium** |

**Python 3.14 key features:**
- PEP 779: Free-threaded Python officially supported
- PEP 649: Deferred evaluation of annotations
- PEP 750: Template string literals (t-strings)
- PEP 734: Multiple interpreters in stdlib
- PEP 784: `compression.zstd` module

**Python 3.12** is past its full support window (ended April 2025) and is now in security-fix-only mode.

**Recommendation:** Upgrade Dockerfiles from `python:3.12-slim` to `python:3.14-slim`. Test thoroughly -- the free-threading and deferred annotations changes may affect some libraries.

### Node.js

| Attribute | Value |
|---|---|
| **Current LTS** | 24.14.0 "Krypton" (Active LTS until April 2028) |
| **Maintenance LTS** | 22.x "Jod" (until April 2027), 20.x "Iron" (until April 2026) |

**Recommendation:** Use Node.js 24.x LTS for the frontend Dockerfile.

---

## Security: OWASP Top 10

### OWASP Top 10:2025 (Web Applications)

| Rank | Category | Change from 2021 |
|---|---|---|
| A01 | Broken Access Control | Unchanged |
| A02 | Security Misconfiguration | Up from #5 |
| A03 | Software Supply Chain Failures | **New** |
| A04 | Cryptographic Failures | Down from #2 |
| A05 | Injection | Down from #3 |
| A06 | Insecure Design | Down from #4 |
| A07 | Authentication Failures | Renamed |
| A08 | Software or Data Integrity Failures | Unchanged |
| A09 | Logging & Alerting Failures | Renamed |
| A10 | Mishandling of Exceptional Conditions | **New** |

**Key takeaway:** Software Supply Chain Failures entering at #3 is directly relevant to the MinIO situation. SSRF merged into Broken Access Control.

### OWASP Top 10 for Agentic Applications (2026)

Directly relevant to MARKAI's LangGraph agents:

| ID | Risk | Relevance |
|---|---|---|
| ASI01 | Agent Goal Hijack | High -- agent prompt injection |
| ASI02 | Tool Misuse & Exploitation | High -- agent tool calling |
| ASI03 | Identity & Privilege Abuse | High -- agent credentials |
| ASI04 | Agentic Supply Chain Vulnerabilities | Medium -- tool descriptors |
| ASI05 | Unexpected Code Execution | High -- if agents generate code |
| ASI06 | Memory & Context Poisoning | High -- RAG/Qdrant stores |
| ASI10 | Rogue Agents | Medium -- agent alignment |

**Recommendations:**
- Implement unique, scoped, short-lived agent identities
- Apply zero-trust principles (least privilege, isolation, mutual auth)
- Add robust observability (logging, anomaly detection)
- Human-in-the-loop governance for high-impact agent actions

---

## Priority Action Items

### Critical (Do Immediately)
1. **MinIO replacement plan** -- repository archived, no security patches
2. **Pin all `:latest` Docker image tags** to specific versions
3. **Traefik upgrade** from v3.2 to v3.6.11 (security patches)
4. **Remove `version: "3.9"`** from docker-compose.yml

### High Priority (Next Sprint)
5. **LangGraph upgrade** from 0.4 to 1.1.0 (production-ready release)
6. **Valkey upgrade** from 8 to 9.0.3 (security fixes)
7. **OpenAI model updates** in LiteLLM config (GPT-4.1 default)
8. **Pin LiteLLM** to specific version

### Medium Priority (Next Quarter)
9. **Next.js 16** migration (async APIs, Turbopack, middleware->proxy)
10. **Auth.js v5** migration (coincide with Next.js 16)
11. **Python 3.14** upgrade in all Dockerfiles
12. **Recharts 3.x** migration
13. **Unified radix-ui** package migration

### Low Priority (Backlog)
14. **APScheduler** bump to 3.11.x
15. **OpenTelemetry** version pinning
16. **Docker Compose** file rename to compose.yaml
17. **Node.js 24 LTS** in frontend Dockerfile
18. **Grafana/Prometheus/Loki** version pinning

---

## Sources

- [Next.js 16.2 Blog Post](https://nextjs.org/blog/next-16-2)
- [Next.js 16 Upgrade Guide](https://nextjs.org/docs/app/guides/upgrading/version-16)
- [FastAPI Releases](https://github.com/fastapi/fastapi/releases)
- [LangGraph 1.0 GA Announcement](https://changelog.langchain.com/announcements/langgraph-1-0-is-now-generally-available)
- [LangGraph PyPI](https://pypi.org/project/langgraph/)
- [LiteLLM Documentation](https://docs.litellm.ai/)
- [LiteLLM PyPI](https://pypi.org/project/litellm/)
- [PostgreSQL 16.13 Release](https://www.postgresql.org/about/news/out-of-cycle-release-scheduled-for-february-26-2026-3241/)
- [Qdrant v1.17.0 Release](https://github.com/qdrant/qdrant/releases/tag/v1.17.0)
- [NATS Server Releases](https://github.com/nats-io/nats-server/releases)
- [MinIO Archived -- InfoQ](https://www.infoq.com/news/2025/12/minio-s3-api-alternatives/)
- [MinIO Alternatives](https://openalternative.co/alternatives/minio)
- [RustFS -- MinIO Alternative](https://github.com/rustfs/rustfs)
- [Valkey 9.0 Release](https://valkey.io/blog/introducing-valkey-9/)
- [Valkey 9.0.3 Security Release](https://github.com/valkey-io/valkey/releases/tag/9.0.3)
- [Traefik Releases](https://github.com/traefik/traefik/releases)
- [Auth.js v5 Migration Guide](https://authjs.dev/getting-started/migrating-to-v5)
- [Playwright Release Notes](https://playwright.dev/docs/release-notes)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/)
- [OpenTelemetry Python SDK PyPI](https://pypi.org/project/opentelemetry-sdk/)
- [Grafana Downloads](https://grafana.com/grafana/download)
- [Prometheus Releases](https://github.com/prometheus/prometheus/releases)
- [Loki Release Notes](https://grafana.com/docs/loki/latest/release-notes/)
- [shadcn/ui Changelog](https://ui.shadcn.com/docs/changelog)
- [Recharts 3.0 Migration Guide](https://github.com/recharts/recharts/wiki/3.0-migration-guide)
- [OpenAI GPT-4.1 Announcement](https://openai.com/index/gpt-4-1/)
- [OpenAI GPT-5.4 Launch](https://techcrunch.com/2026/03/05/openai-launches-gpt-5-4-with-pro-and-thinking-versions/)
- [Microsoft Fabric March 2026 Feature Summary](https://blog.fabric.microsoft.com/en-us/blog/fabric-march-2026-feature-summary/)
- [Docker Compose File Reference](https://docs.docker.com/reference/compose-file/)
- [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [Python 3.14 Release Notes](https://docs.python.org/3/whatsnew/3.14.html)
- [Node.js Releases](https://nodejs.org/en/about/previous-releases)
