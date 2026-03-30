# Phase 11: Documentation & Developer Experience Audit

**Date:** 2026-03-30
**Auditor:** Claude Opus 4.6 (automated)
**Scope:** All documentation, DX tooling, onboarding readiness

---

## 11.1 Documentation Completeness

### 11.1.1 README.md

| Check | Status | Details |
|-------|--------|---------|
| README.md exists at repo root | **FAIL** | No `README.md` file exists at `D:\MarkAI\README.md` |

**Impact: Critical.** A missing README is the single largest barrier to onboarding. GitHub/GitLab renders the README as the project landing page. Without it, a new developer has zero orientation.

**Recommendation:** Create a `README.md` covering: project description, architecture overview (can reference `docs/build-files/SYSTEM-ARCHITECTURE.md`), quickstart (local dev setup in <5 steps), env var setup, link to deployment docs, link to API docs, team/contact info.

---

### 11.1.2 Existing Markdown Documentation Inventory

| File | Purpose | Quality |
|------|---------|---------|
| `docs/build-files/SYSTEM-ARCHITECTURE.md` | Full architecture with Mermaid diagrams, data flow, NATS streams, scheduler jobs, API map, auth flow, LangGraph workflows | **Excellent** -- comprehensive, well-structured, includes 10 sections |
| `docs/build-files/MARKAI-Setup-Guide-v2.md` | Manual setup: Entra ID, Fabric, OpenAI, social APIs, VPS prep, n8n, pre-flight checklist | **Excellent** -- step-by-step with env var tables |
| `docs/build-files/MARKAI-Implementation-Plan-v2.md` | Full coding agent prompt: tech stack, repo structure, critical rules | **Good** -- more of a build spec than ongoing docs |
| `docs/build-files/MARKAI-n8n-Workflows-v2.md` | n8n workflow design: payload contracts, 3 publish workflows | **Good** |
| `docs/build-files/SETUP-REMAINING.md` | Checklist of post-build config items | **Good** -- actionable checklist format |
| `docs/build-files/TECHNOLOGY_RESEARCH_MARCH_2026.md` | Stack version audit: Next.js, FastAPI, LangGraph, etc. | **Good** -- thorough research |
| `docs/build-files/DEPENDENCY-AUDIT.md` | Package-level dependency audit with action items | **Good** |
| `docs/build-files/AUDIT-REPORT.md` | Final audit scorecard: 23/23 checks passing | **Good** |
| `docs/build-files/universal-audit-loop-prompt.md` | 5-cycle audit methodology prompt | **Informational** -- meta/process doc |
| `docs/build-files/AUDIT-FIX-LOOP-AGENT-PROMPT.md` | Agent prompt for audit fixing | **Informational** -- meta/process doc |
| `docs/n8n-workflows/README.md` | n8n workflow setup, channel support table, node versions | **Good** |
| `docs/VPS_DEPLOY_SHARED_TRAEFIK.md` | Production VPS deployment with shared Traefik | **Excellent** -- includes rollback, update, troubleshooting sections |
| `MASTER_IMPLEMENTATION_PLAN.md` | Current sprint plan: 7 issues across pipeline/rendering/UX | **Good** -- live working doc |

**Total project markdown files: 13** (excluding node_modules)

---

### 11.1.3 API Documentation

| Check | Status | Details |
|-------|--------|---------|
| OpenAPI/Swagger auto-docs | **PARTIAL** | FastAPI generates `/docs` (Swagger UI) and `/redoc` automatically by default. No explicit `docs_url=None` found, so these endpoints should be live. However, there is no custom configuration (`docs_url`, `redoc_url`, `openapi_url`) -- purely default FastAPI behavior. |
| API endpoint map | **PASS** | `SYSTEM-ARCHITECTURE.md` section 8 lists all 18 route prefixes with purpose and auth level |
| Request/response schemas | **PARTIAL** | Pydantic models serve as implicit docs via FastAPI's auto-generated OpenAPI spec. No standalone API reference docs exist. |
| Webhook contracts | **PASS** | `MARKAI-n8n-Workflows-v2.md` documents the publish webhook payload contract |

**Recommendation:** Verify that FastAPI `/docs` is accessible in development. Consider adding route-level docstrings to improve the auto-generated Swagger descriptions.

---

### 11.1.4 Architecture Documentation

| Check | Status | Details |
|-------|--------|---------|
| System architecture diagram | **PASS** | Mermaid diagram in `SYSTEM-ARCHITECTURE.md` with 16 Docker services, edge/app/data/infra/observability layers |
| Data flow documentation | **PASS** | 12-step lifecycle from brand onboarding to adaptation loop |
| Content status state machine | **PASS** | Mermaid stateDiagram with 8 states and transitions |
| NATS event streams | **PASS** | 8 streams, 7 consumers documented with Mermaid |
| Authentication flow | **PASS** | Full auth flow documented (Entra ID -> JWT -> role check) |
| Scheduler jobs | **PASS** | 5 jobs with schedules and descriptions |
| LangGraph workflows | **PASS** | 7 graphs documented with node counts and human-in-loop flags |

**Verdict: Architecture documentation is strong.** The `SYSTEM-ARCHITECTURE.md` file is one of the best-documented aspects of the project.

---

### 11.1.5 Contributing Guide

| Check | Status |
|-------|--------|
| CONTRIBUTING.md | **MISSING** |
| Code style guide | **MISSING** (ruff is configured but no documented style conventions) |
| PR template | **MISSING** |
| Issue template | **MISSING** |

---

### 11.1.6 Code Comments & Docstrings

| Area | Files | Docstrings Found | Coverage |
|------|-------|-----------------|----------|
| Backend (`backend/app/`) | 81 `.py` files | 7 module-level docstrings across 4 files | **Very Low (~5%)** |
| Agents (`agents/`) | 48 `.py` files | 42 module-level docstrings across 37 files | **Good (~77%)** |
| Frontend (`frontend/src/`) | 79 `.ts`/`.tsx` files | Not measured (TypeScript) | Unknown |

- **Backend** has almost no module-level docstrings. Most route files jump straight into imports with no module doc.
- **Agents** have good docstring coverage -- most files document their purpose.
- No `TODO`, `FIXME`, or `HACK` comments found anywhere in backend, agents, or frontend source -- this is clean.

**Recommendation:** Add module-level docstrings to all backend route files and service modules. Add function-level docstrings to complex business logic (scheduler, publish service, NATS consumer).

---

### 11.1.7 Changelog

| Check | Status |
|-------|--------|
| CHANGELOG.md | **MISSING** |
| Git commit messages | **Decent** -- recent commits use conventional-ish format (`fix:`, `docs:`) |

**Recommendation:** Either maintain a `CHANGELOG.md` or adopt a tool like `git-cliff` / conventional-changelog to auto-generate from commit messages.

---

## 11.2 Developer Experience

### 11.2.1 Can a New Developer Set Up from README Alone?

**No.** There is no README. A developer would need to:
1. Discover `docs/build-files/MARKAI-Setup-Guide-v2.md` for env var setup
2. Discover `docs/VPS_DEPLOY_SHARED_TRAEFIK.md` for deployment
3. Guess that `docker compose up -d` works locally (documented only as a comment in `docker-compose.yml` line 3)

The setup guide is thorough but is buried in `docs/build-files/` and targeted at production/VPS deployment, not local dev quickstart.

**Recommendation:** Create a README with a "Local Development" quickstart section:
```
1. cp .env.example .env   # fill in secrets
2. docker compose up -d   # auto-loads override for local dev
3. python scripts/seed-dev.py  # seed test data
4. Open http://localhost:3000
```

---

### 11.2.2 Development Container / Devcontainer

| Check | Status |
|-------|--------|
| `.devcontainer/` directory | **MISSING** |
| `devcontainer.json` | **MISSING** |

**Impact:** No VS Code / Codespaces / GitHub Codespaces one-click setup. Developers must manually install Docker, Python, Node.js, etc.

**Recommendation:** Low priority given Docker Compose handles all services. But a devcontainer for the frontend or backend alone would help contributors who want to work outside Docker.

---

### 11.2.3 Seed / Fixture Script

| Check | Status | Details |
|-------|--------|---------|
| Seed script exists | **PASS** | `scripts/seed-dev.py` -- creates a test brand + 4 prompt versions via the API |
| Seed is documented | **PARTIAL** | Script has a good module docstring with usage, but is not referenced in any setup guide |
| Fixture data | **N/A** | No SQL fixtures; seed goes through the API (good pattern for schema validation) |

**Recommendation:** Reference `scripts/seed-dev.py` in the README quickstart.

---

### 11.2.4 Hot Reload

| Service | Hot Reload | Mechanism |
|---------|-----------|-----------|
| Backend | **YES** | `docker-compose.override.yml` line 46: `uvicorn ... --reload` + volume mount `./backend/app:/app/app` |
| Frontend | **PARTIAL** | Port 3000 exposed but **no volume mount** for frontend source in override. Next.js runs `next dev` (from `package.json`) but changes require container rebuild. |
| Agents | **YES** | Volume mounts `./agents/shared:/app/shared` and `./agents/workflows:/app/workflows` |
| Browser Worker | **YES** | Volume mount `./browser-worker/app:/app/app` |
| Notifications | **NO** | No volume mount, no reload flag |

**Issue: Frontend has no hot reload in Docker.** The `docker-compose.override.yml` exposes port 3000 but does not mount the frontend source directory. Developers must rebuild the frontend container after every change.

**Recommendation:** Add to `docker-compose.override.yml` under `frontend`:
```yaml
  frontend:
    ports:
      - "3000:3000"
    volumes:
      - ./frontend/src:/app/src
      - ./frontend/public:/app/public
    command: npm run dev
```

---

### 11.2.5 Helpful Scripts

| Script | Purpose | Documented |
|--------|---------|-----------|
| `scripts/seed-dev.py` | Seed test brand + prompts | In docstring only |
| `scripts/bc-table-discovery.py` | Discover Business Central table names in Fabric | Referenced in Setup Guide |
| `scripts/column-discovery.py` | Discover column names in BC tables | Not documented |

**Missing scripts that would improve DX:**
- `scripts/reset-db.sh` -- drop and recreate database
- `scripts/run-migrations.sh` -- run Alembic migrations
- No `Makefile` or task runner (no `make dev`, `make test`, `make lint`, etc.)

**Recommendation:** Add a `Makefile` with common targets: `dev`, `build`, `test`, `lint`, `seed`, `migrate`, `reset-db`, `logs`.

---

### 11.2.6 Pre-commit Hooks

| Check | Status |
|-------|--------|
| `.pre-commit-config.yaml` | **MISSING** |
| `.husky/` directory | **MISSING** |
| Any git hooks | **NONE** |

**Impact:** No automated lint/format checks before commit. Ruff is listed as a dev dependency in `backend/pyproject.toml` and ESLint is configured for the frontend, but neither runs automatically.

**Recommendation:** Add either:
- `pre-commit` (Python ecosystem) with ruff + eslint hooks, or
- Husky (Node ecosystem) with lint-staged

---

### 11.2.7 Editor Configuration

| Check | Status |
|-------|--------|
| `.editorconfig` | **MISSING** at project root |
| `.vscode/` settings | **MISSING** (also in `.gitignore` under "IDE") |
| `.vscode/extensions.json` | **MISSING** |
| `.vscode/launch.json` | **MISSING** |
| `.prettierrc` | **MISSING** |

**Impact:** No shared editor settings. Different developers may use different indentation, line endings, trailing whitespace behavior. The `.gitignore` explicitly excludes `.vscode/`, which prevents sharing debug configs and recommended extensions.

**Recommendation:**
1. Add `.editorconfig` at project root (indent_style, indent_size, end_of_line, charset, trim_trailing_whitespace)
2. Consider removing `.vscode/` from `.gitignore` and adding `.vscode/settings.json` + `.vscode/extensions.json` (recommended extensions: Python, ESLint, Prettier, Tailwind CSS IntelliSense, Docker)
3. Add `.vscode/launch.json` with debug configurations for FastAPI backend and Next.js frontend

---

### 11.2.8 Debug Configurations

| Check | Status |
|-------|--------|
| VS Code launch.json | **MISSING** |
| PyCharm run configs | **MISSING** |
| Docker debug setup | **NONE** |

**No debug configurations exist.** A developer must manually configure their IDE to attach to the FastAPI or Next.js process.

---

### 11.2.9 Linting & Formatting

| Tool | Configured | Runs Automatically |
|------|-----------|-------------------|
| Ruff (Python) | Listed in `backend/pyproject.toml` dev deps | **No** -- no pre-commit, no CI |
| ESLint (Frontend) | `frontend/eslint.config.mjs` with Next.js + TypeScript rules | **No** -- `npm run lint` exists but no pre-commit |
| Prettier | **Not configured** | N/A |
| Type checking (mypy/pyright) | **Not configured** for Python | N/A |
| TypeScript strict mode | Unknown (would need tsconfig check) | N/A |

---

### 11.2.10 Environment Variable Management

| Check | Status | Details |
|-------|--------|---------|
| `.env.example` | **PASS** | Exists with all keys and placeholder values |
| `.env.vps.example` | **PASS** | Exists for VPS deployment |
| `.env` in `.gitignore` | **PASS** | `.env`, `.env.local`, `.env.production` all ignored |
| Env var validation | **PASS** | Pydantic Settings used in backend |

---

### 11.2.11 Docker & Build

| Check | Status | Details |
|-------|--------|---------|
| Dockerfiles | **PASS** | 5 Dockerfiles: backend, frontend, agents, browser-worker, notifications |
| docker-compose.yml | **PASS** | Well-structured base with no host port bindings |
| docker-compose.override.yml | **PASS** | Local dev overrides with ports + hot reload (partial) |
| docker-compose.vps.yml | **PASS** | Production overlay with Traefik labels |
| Build documentation | **PASS** | Comments in compose files explain usage |

---

### 11.2.12 Test Infrastructure

| Check | Status | Details |
|-------|--------|---------|
| Test framework configured | **PARTIAL** | `pytest` + `pytest-asyncio` in dev deps for backend, browser-worker, notifications |
| Test files exist | **FAIL** | **Zero test files found** anywhere in the project |
| Test runner script | **MISSING** | No `npm test`, no `make test`, no CI test step |
| Frontend test framework | **MISSING** | No jest/vitest/playwright-test configured in `package.json` |

**Impact: Critical.** Despite pytest being listed as a dev dependency, there are zero actual test files. The project has 208 source files (81 backend + 48 agents + 79 frontend) with 0% test coverage.

---

## Summary Scorecard

| Category | Score | Verdict |
|----------|-------|---------|
| Architecture docs | 9/10 | Excellent -- `SYSTEM-ARCHITECTURE.md` is thorough |
| Setup/deployment docs | 8/10 | Good -- detailed but scattered across multiple files |
| README | 0/10 | **Missing entirely** |
| API docs | 5/10 | FastAPI auto-docs only; no custom descriptions |
| Contributing guide | 0/10 | Missing |
| Changelog | 0/10 | Missing |
| Code comments (agents) | 7/10 | Good docstring coverage |
| Code comments (backend) | 2/10 | Almost no docstrings |
| Hot reload | 6/10 | Backend + agents good; frontend broken in Docker |
| Seed scripts | 7/10 | Exists but undiscoverable |
| Pre-commit hooks | 0/10 | None |
| Editor config | 0/10 | No `.editorconfig`, no shared VS Code settings |
| Debug configs | 0/10 | None |
| Test infrastructure | 1/10 | Framework listed but zero tests |
| Task runner / Makefile | 0/10 | None |
| **Overall DX Score** | **3.0/10** | **Significant gaps** |

---

## Priority Recommendations

### P0 -- Must Fix Before Onboarding Any Developer

1. **Create `README.md`** with project overview, local quickstart (5 steps), links to detailed docs
2. **Create tests** -- at minimum, smoke tests for API health + one integration test per major workflow
3. **Fix frontend hot reload** -- add volume mount in `docker-compose.override.yml`

### P1 -- Should Fix Soon

4. **Add `Makefile`** with common targets (`dev`, `build`, `test`, `lint`, `seed`, `logs`)
5. **Add `.editorconfig`** for consistent formatting across editors
6. **Add pre-commit hooks** (ruff for Python, eslint for TypeScript)
7. **Add backend docstrings** to all route modules and service functions
8. **Add `CONTRIBUTING.md`** with branching strategy, PR process, coding standards

### P2 -- Nice to Have

9. **Add VS Code recommended extensions** (`.vscode/extensions.json`)
10. **Add VS Code debug configs** (`.vscode/launch.json`)
11. **Add `CHANGELOG.md`** or auto-generate from conventional commits
12. **Add `.devcontainer/`** for Codespaces support
13. **Consolidate setup docs** -- the 6 files in `docs/build-files/` overlap; a single "Developer Guide" would be clearer
14. **Add route-level docstrings** to FastAPI endpoints for better Swagger UI
