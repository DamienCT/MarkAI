# Git Analysis — MARKAI Project

Generated: 2026-03-30

---

## 1. Last 100 Commits — Summary

**Date range:** 2026-03-24 to 2026-03-30 (7 days, 49 commits)

> Note: The entire repo history spans only ~7 days. All 49 commits fall within the last 100 window.

### Commit Type Breakdown

| Type | Count | Percentage |
|------|-------|-----------|
| `fix:` | 31 | 63% |
| `feat:` | 13 | 27% |
| `docs:` / `chore:` | 5 | 10% |

### Commits Per Day

| Date | Commits |
|------|---------|
| 2026-03-29 | 12 |
| 2026-03-30 | 11 |
| 2026-03-27 | 11 |
| 2026-03-28 | 9 |
| 2026-03-24 | 6 |

### Key Patterns

1. **Fix-heavy history (63% fix commits):** The project has a very high fix-to-feature ratio, indicating rapid iteration followed by significant bug-fixing and stabilization passes.

2. **Audit-driven development:** At least 6 commits are explicitly audit-related, including massive batch fixes:
   - `3c73767` — "implement all 147 audit findings"
   - `e9a134f` — "full verification audit — 83 bugs found and fixed across 3 audit passes"
   - `c5bf198` — "v5 audit — zero hardcoded models, workflow error routing, schema alignment"

3. **Deployment stabilization cluster (2026-03-27 to 2026-03-28):** ~15 commits focused on VPS deployment, Docker, Traefik, HTTPS, mixed content, and auth token issues. This indicates the first real deployment encountered many environment-specific issues.

4. **Large monolithic commits:** Several commits touch dozens of files simultaneously (e.g., audit fix commits, v1.0 initial commit). This makes it hard to isolate regressions.

5. **Brand activation flow (2026-03-29):** Multiple commits refining the onboarding-to-activation pipeline, with repeated fixes to the same components (BrandOnboarding, overview page, agent_runs schema).

---

## 2. File Hotspots (Most Frequently Changed)

Top 30 files by change frequency across last 100 commits:

| Changes | File | Category |
|---------|------|----------|
| 9 | `agents/workflows/planning/nodes.py` | Agent logic |
| 8 | `db/init.sql` | Database schema |
| 8 | `agents/workflows/content/nodes.py` | Agent logic |
| 7 | `frontend/src/lib/api.ts` | Frontend API layer |
| 7 | `frontend/src/app/brands/[id]/page.tsx` | Brand overview page |
| 7 | `frontend/Dockerfile` | Infrastructure |
| 7 | `backend/app/api/v1/intelligence.py` | Backend API |
| 7 | `agents/workflows/research/nodes.py` | Agent logic |
| 7 | `agents/shared/tools/database.py` | Shared DB tools |
| 6 | `frontend/src/types/index.ts` | TypeScript types |
| 6 | `frontend/src/components/brand/BrandOnboarding.tsx` | UI component |
| 6 | `docker-compose.yml` | Infrastructure |
| 6 | `agents/workflows/planning/state.py` | Agent state |
| 6 | `agents/worker.py` | Agent worker |
| 6 | `DEPLOY_FIX.md` | Documentation |
| 5 | `frontend/src/app/settings/users/page.tsx` | Settings UI |
| 5 | `frontend/src/app/settings/page.tsx` | Settings UI |
| 5 | `backend/app/scheduler/morning_jobs.py` | Scheduler |
| 5 | `backend/app/config.py` | Backend config |
| 5 | `backend/Dockerfile` | Infrastructure |
| 5 | `agents/workflows/strategy/nodes.py` | Agent logic |
| 5 | `agents/workflows/product_intel/nodes.py` | Agent logic |
| 5 | `agents/workflows/evaluation/nodes.py` | Agent logic |
| 5 | `agents/workflows/content/graph.py` | Agent graph |
| 5 | `agents/shared/llm.py` | LLM configuration |
| 4 | `frontend/src/lib/auth.ts` | Auth layer |
| 4 | `frontend/src/components/layout/Sidebar.tsx` | Navigation |
| 4 | `frontend/src/components/content/CalendarView.tsx` | Calendar UI |
| 4 | `frontend/src/components/brand/tabs/ProductsTab.tsx` | Products UI |

### Hotspot Analysis

- **Agent workflow nodes** are the highest-churn area (planning, content, research, strategy, product_intel, evaluation nodes all in top 30). These files are the core AI logic and have been touched in nearly every audit pass.
- **`db/init.sql`** changed 8 times — schema is still evolving rapidly, suggesting the data model is not yet stable.
- **`frontend/Dockerfile`** changed 7 times — deployment configuration was repeatedly adjusted, indicating Docker build issues.
- **`frontend/src/lib/api.ts`** changed 7 times — the API client layer needed repeated fixes (HTTPS, auth tokens, error handling).

---

## 3. Stale Files (Not Changed Since Initial Commit)

The following files have not been modified since the initial v1.0 commit on 2026-03-24 and may contain stale or untested code:

### Agent Layer (Stale Since v1.0)
- `agents/__init__.py`
- `agents/shared/__init__.py`
- `agents/shared/state.py`
- `agents/shared/tools/__init__.py`
- `agents/shared/tools/image_search.py`
- `agents/shared/tools/web_search.py`
- `agents/workflows/__init__.py`
- `agents/workflows/adaptation/__init__.py`
- `agents/workflows/adaptation/nodes.py`
- `agents/workflows/adaptation/state.py`
- `agents/workflows/content/__init__.py`
- `agents/workflows/content/image_sourcing.py`
- `agents/workflows/evaluation/__init__.py`
- `agents/workflows/evaluation/state.py`
- `agents/workflows/planning/__init__.py`
- `agents/workflows/product_intel/__init__.py`
- `agents/workflows/product_intel/state.py`
- `agents/workflows/research/__init__.py`
- `agents/workflows/research/state.py`
- `agents/workflows/strategy/__init__.py`

### Backend Layer (Stale Since v1.0)
- `backend/alembic.ini`
- `backend/alembic/versions/.gitkeep`
- `backend/app/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/api/v1/__init__.py`
- `backend/app/api/v1/campaigns.py`
- `backend/app/api/v1/content.py`
- `backend/app/api/v1/dashboard.py`
- `backend/app/api/v1/learning.py`

### Other
- `.env.example`

### Notable Observations
- The **adaptation workflow** (`agents/workflows/adaptation/`) has never been modified after initial creation — it may be entirely untested or unused.
- **`backend/app/api/v1/campaigns.py`**, **`content.py`**, **`dashboard.py`**, **`learning.py`** — core API routes that were never touched after v1.0. Either they were perfect from the start (unlikely given the fix rate elsewhere) or they lack real usage/testing.
- **Alembic** migrations directory has only a `.gitkeep` — no migrations have ever been created, meaning all schema changes go through `db/init.sql` directly. This is a risk for production deployments.

---

## 4. Reverted and Fixup Commits

**No explicit `revert:` or `fixup!` commits found** in the last 100 commits.

However, there are implicit fix-chains where a feature commit is immediately followed by one or more fix commits targeting the same area:

| Feature/Change | Subsequent Fixes |
|---------------|-----------------|
| `2f46d11` feat: brand activation flow | `afe9090` fix: onboarding progress mismatch, `7785062` fix: activation CHECK constraint, `83b8536` fix: overview page Start button |
| `269611a` feat: VPS deployment | `7e57959` fix: adapt to shared Traefik, `1f41198` fix: harden Docker build, `d8b0b9a` fix: remove hard public copy, `42ce664` fix: pin Playwright cache, `c12ebd8` fix: frontend 404 |
| `96a771b` feat: content engine | `5975e45` fix: auto-discover pipeline trigger, `957ecc9` fix: image proxy auth |
| `e9a134f` fix: 83 audit bugs | `c5bf198` fix: v5 audit (more issues found) |

This pattern of feature-then-multiple-fixes suggests features are being committed before adequate local testing.

---

## 5. TODO / FIXME / HACK / WORKAROUND / XXX / TEMP Comments

### Source Code

**No TODO, FIXME, HACK, WORKAROUND, or TEMP comments found in application source code** (Python, TypeScript, SQL, YAML, shell scripts).

This is a positive finding — prior audit commits explicitly cleaned these up.

### Non-Code Occurrences (Documentation / Config Only)

| File | Match | Context |
|------|-------|---------|
| `frontend/package-lock.json:3077` | `XXX` | Part of an npm integrity hash — **false positive** |
| `MASTER_AUDIT_PROMPT.md` (multiple lines) | `TODO`, `FIXME`, `HACK`, `XXX`, `TEMP` | Template text in audit prompt documentation — **not code issues** |
| `docs/build-files/AUDIT-REPORT.md:49` | `TODO/FIXME/HACK` | Audit checklist reference — **not a code issue** |
| `docs/build-files/universal-audit-loop-prompt.md` (multiple) | `TODO`, `TEMP` | Audit prompt template — **not code issues** |

### Verdict

**CLEAN** — Zero actionable TODO/FIXME/HACK comments exist in the application codebase.

---

## 6. Summary of Risks

| Risk | Severity | Details |
|------|----------|---------|
| High fix-to-feature ratio | Medium | 63% of commits are fixes. Suggests inadequate pre-commit testing. |
| Monolithic commits | Medium | Audit fix commits touch 50+ files at once, making rollback difficult. |
| Schema instability | High | `db/init.sql` changed 8 times with no Alembic migrations — unsafe for production data. |
| Untested adaptation workflow | Medium | `agents/workflows/adaptation/` untouched since v1.0 — likely dead or untested code. |
| Stale backend routes | Medium | `campaigns.py`, `content.py`, `dashboard.py`, `learning.py` never modified post-v1.0. |
| Deployment churn | Low | 7 Docker/deployment fixes in 2 days — now stabilized but indicates fragile infra config. |
| No migration tooling | High | Alembic is configured but never used. All schema changes are in `init.sql`. |
