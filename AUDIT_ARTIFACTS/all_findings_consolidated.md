# MARKAI Audit — All Findings Consolidated Summary

**Generated:** 2026-03-30
**Source:** 14 audit artifacts (Phases 1-11)
**Full remediation details:** `AUDIT_ARTIFACTS/MASTER_REMEDIATION_PLAN.md`

---

## Counts by Severity

| Severity | Count |
|----------|-------|
| CRITICAL | 16 |
| HIGH | 38 |
| MEDIUM | 30 |
| LOW | 25 |
| **Total** | **109** |

Note: Some findings from multiple audit phases were deduplicated into single entries in the Master Remediation Plan (97 unique findings). The raw counts above reflect deduplicated totals.

---

## Counts by Remediation Phase

| Phase | Description | Finding Count | Severities |
|-------|-------------|---------------|------------|
| **A** | Critical Security Fixes | 24 | 9 CRITICAL, 9 HIGH, 6 MEDIUM |
| **B** | Critical Bug Fixes | 17 | 7 CRITICAL, 8 HIGH, 2 MEDIUM |
| **C** | High-Severity Fixes | 16 | 1 CRITICAL, 13 HIGH, 2 MEDIUM |
| **D** | Database & Schema Fixes | 10 | 0 CRITICAL, 2 HIGH, 5 MEDIUM, 3 LOW |
| **E** | Performance Fixes | 16 | 0 CRITICAL, 5 HIGH, 11 MEDIUM |
| **F** | Medium-Severity Fixes | 25 | 0 CRITICAL, 2 HIGH, 23 MEDIUM |
| **G** | Low-Severity & Polish | 25 | 0 CRITICAL, 1 HIGH, 2 MEDIUM, 22 LOW |

---

## Counts by Category

| Category | Count |
|----------|-------|
| Security (auth, secrets, injection, access control) | 24 |
| Performance (blocking I/O, N+1, caching, pooling) | 18 |
| Bugs (runtime crashes, incorrect queries, race conditions) | 17 |
| Infrastructure (Docker, compose, monitoring, CI/CD) | 14 |
| Frontend (state mgmt, responsive, a11y, bundle) | 12 |
| Database (schema, indexes, migrations, constraints) | 10 |
| Code Quality (patterns, consistency, dead code) | 8 |
| Documentation & DX (README, tests, tooling) | 6 |

---

## Top 10 Most Critical Findings

| # | ID | Severity | Summary |
|---|-----|----------|---------|
| 1 | BUG-001 | CRITICAL | `get_performance_data` references non-existent `measured_at` column — crashes at runtime |
| 2 | BUG-002 | CRITICAL | `store_adaptations` inserts into non-existent columns — crashes at runtime |
| 3 | BUG-003 | CRITICAL | `upsert_product` ON CONFLICT on non-existent unique constraint — crashes at runtime |
| 4 | BUG-004 | CRITICAL | MemorySaver checkpointer causes unbounded memory growth (OOM) in production |
| 5 | SEC-005 | CRITICAL | Generic `execute_query`/`execute_update` accept arbitrary SQL — injection risk |
| 6 | SEC-006 | CRITICAL | No rate limiting anywhere — financial abuse via LLM endpoints |
| 7 | SEC-003 | CRITICAL | Unauthenticated file proxy serves all MinIO content |
| 8 | SEC-004 | CRITICAL | Social platform access tokens exposed in frontend API responses |
| 9 | PERF-001 | CRITICAL | Blocking pyodbc calls in async context stall entire event loop |
| 10 | BUG-006 | CRITICAL | Race condition in idempotency check (TOCTOU) allows duplicate workflows |

---

## Findings by Source Audit

### Phase 1: Backend Audit
- 3 CRITICAL, 12 HIGH, 19 MEDIUM, 13 LOW = **47 findings**

### Phase 1: Agents Audit
- 5 CRITICAL, 14 HIGH, 19 MEDIUM, 12 LOW = **50 findings**

### Phase 1: Frontend Audit
- 2 CRITICAL, 11 HIGH, 19 MEDIUM, 12 LOW = **44 findings**

### Phase 1: Infrastructure Audit
- 3 CRITICAL, 12 HIGH, 18 MEDIUM, 11 LOW = **44 findings**

### Phase 2: Dependency Audit
- 3 CRITICAL (security advisories), 5 HIGH, 3 MEDIUM, 2 LOW = **13 findings**

### Phase 3: AI/ML Model Audit
- 3 CRITICAL, 5 HIGH, 5 MEDIUM = **13 findings**

### Phase 4: Security Audit
- 0 CRITICAL, 5 HIGH, 10 MEDIUM, 6 LOW = **21 findings**

### Phase 5: Performance Audit
- 1 CRITICAL, 11 HIGH, 19 MEDIUM, 10 LOW = **41 findings**

### Phase 6: Database Audit
- 4 CRITICAL, 3 HIGH, 7 MEDIUM, 5 LOW = **19 findings**

### Phase 7: API Contract Audit
- 4 CRITICAL, 6 HIGH, 8 MEDIUM, 5 LOW = **23 findings**

### Phase 8: Frontend UX Audit
- 3 CRITICAL, 6 HIGH, 13 MEDIUM, 7 LOW = **29 findings**

### Phase 9: Infrastructure/DevOps Audit
- 0 CRITICAL, 1 HIGH, 8 MEDIUM, 9 LOW = **18 findings** (+ 3 INFO)

### Phase 10: Code Quality Audit
- 4 CRITICAL (FAIL), 10 WARN = **14 findings**

### Phase 11: Documentation Audit
- DX Score: 3.0/10 — **12 gap areas identified**

---

## Files Most Frequently Cited

| File | Times Referenced | Key Issues |
|------|-----------------|------------|
| `agents/shared/tools/database.py` | 12 | SQL injection risk, broken queries, N+1 patterns |
| `backend/app/api/v1/brands.py` | 8 | Missing auth on logo, authorization gaps, transaction issues |
| `docker-compose.yml` | 8 | Hardcoded creds, weak defaults, missing resource limits |
| `backend/app/services/fabric_service.py` | 5 | Blocking sync I/O, no connection pooling |
| `agents/worker.py` | 5 | God function, race condition, chain errors |
| `backend/app/api/v1/analytics.py` | 5 | N+1 queries, no caching, unbounded scans |
| `backend/app/api/v1/products.py` | 5 | No file validation, sequential processing |
| `backend/app/auth/entra.py` | 4 | Blocking JWKS, race condition, unbounded filter |
| `backend/app/api/v1/files.py` | 4 | Unauthenticated access |
| `frontend/src/app/brands/[id]/page.tsx` | 4 | 920-line god component, prop drilling |

---

## Status Summary

| Status | Count |
|--------|-------|
| `[ ] NOT STARTED` | 97 |
| `[x] COMPLETED` | 0 |
| `[~] IN PROGRESS` | 0 |

---

## Recommended Sprint Plan

### Sprint 1 (Immediate — Days 1-3)
**Focus: Stop the bleeding**
1. Fix 3 broken queries (BUG-001, BUG-002, BUG-003) — runtime crashes
2. Pin litellm==1.82.6 (SEC-016) — supply chain risk
3. Add auth to file proxy (SEC-003) — unauthenticated access
4. Add manager role to activate/onboarding (SEC-015) — 5-min fix
5. Remove duplicate endpoints with weaker auth (SEC-022) — 15-min fix

### Sprint 2 (Week 1)
**Focus: Security hardening**
6. Add rate limiting (SEC-006)
7. Mask tokens in API responses (SEC-004)
8. Enable Valkey/NATS/Qdrant authentication (SEC-007, SEC-008, SEC-009)
9. Add file upload validation (SEC-014)
10. Replace MemorySaver with persistent checkpointer (BUG-004)
11. Fix idempotency race condition (BUG-006)

### Sprint 3 (Week 2)
**Focus: Performance + stability**
12. Fix blocking sync I/O (PERF-001, PERF-002, PERF-003)
13. Consolidate analytics/dashboard queries (PERF-010, PERF-011)
14. Add Valkey caching for analytics (PERF-013)
15. Batch BC product sync commits (PERF-014)
16. Add Pydantic enum validation (VAL-001)

### Sprint 4 (Week 3-4)
**Focus: Database + infrastructure**
17. Initialize Alembic migrations (DB-001)
18. Add missing indexes and constraints (DB-002, DB-003, DB-006, DB-008)
19. Create CI/CD pipeline (MISC-005)
20. Add smoke tests (MISC-006)
21. Enable image optimization (PERF-015)
22. Fix frontend god component (FIX-007)

### Backlog
Everything in Phase F and Phase G, ordered by impact.

---

*Generated from 14 audit phases. See `MASTER_REMEDIATION_PLAN.md` for full details on each finding.*
