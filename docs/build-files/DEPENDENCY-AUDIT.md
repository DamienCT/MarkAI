# MARKAI — Dependency Audit Report

**Date:** March 24, 2026

---

## Critical Alerts

| # | Issue | Impact | Action |
|---|-------|--------|--------|
| 1 | **MinIO Docker image DISCONTINUED** | Images pulled, repo archived Feb 2026 | Switch to `cgr.dev/chainguard/minio` |
| 2 | **python-jose ABANDONED** (last release 2021) | Known CVEs in ecdsa dep | Replace with `PyJWT` |
| 3 | **passlib[bcrypt] UNMAINTAINED** (last release 2020) | Broken with bcrypt>=5 | Replace with `pwdlib` or direct `bcrypt` |
| 4 | **next-auth v4 EOL** | v4.24.13 is final release | Migrate to Auth.js v5 |
| 5 | **n8n 1.x → 2.x** major breaking changes | Workflow publish model changed | Use migration tool before upgrading |

---

## Python Backend

| Package | Current | Latest | Action |
|---------|---------|--------|--------|
| fastapi | >=0.115 | 0.135.2 | Update |
| sqlalchemy | >=2.0 | 2.0.48 | Update |
| pydantic | >=2.0 | 2.12.5 | Update |
| **python-jose** | unpinned | 3.3.0 (2021) | **REPLACE with PyJWT** |
| **passlib** | unpinned | 1.7.4 (2020) | **REPLACE with pwdlib** |
| redis | >=5.0 | 7.1.1 | Update (2 major behind) |
| httpx | unpinned | 0.28.1 | Pin |
| apscheduler | >=3.10 | 3.11.2 | Update |
| pyodbc | unpinned | 5.3.0 | Pin |
| minio | unpinned | 7.2.20 | Pin |
| qdrant-client | unpinned | 1.17.1 | Pin |
| nats-py | unpinned | 2.14.0 | Pin |
| opentelemetry-* | unpinned | 1.40.0 | Pin |

## Python Agents

| Package | Current | Latest | Action |
|---------|---------|--------|--------|
| **langgraph** | >=0.4 | **1.1.0** | **Major upgrade (GA)** |
| **langchain-core** | >=0.3 | **1.2.20** | **Major upgrade (GA)** |
| **langchain-openai** | >=0.3 | **1.1.12** | **Major upgrade** |
| playwright | unpinned | 1.58.0 | Pin |

## Node.js Frontend

| Package | Current | Latest | Action |
|---------|---------|--------|--------|
| **next** | ^15.1.0 | **16.2.1** | **Major** (async APIs, Turbopack) |
| **next-auth** | ^4.24.11 | 4.24.13 (EOL) | **Migrate to v5** |
| **tailwindcss** | ^3.4.17 | **4.2.2** | **Major** (CSS-first config) |
| **recharts** | ^2.15.0 | **3.8.0** | **Major** (API changes) |
| **lucide-react** | ^0.468.0 | **1.0.1** | **Major** (GA) |
| @radix-ui/* (8 pkgs) | various | unified `radix-ui` 1.4.3 | Consolidate |
| react/react-dom | ^19.0.0 | 19.2.4 | Update |

## Docker Images

| Image | Current | Latest | Action |
|-------|---------|--------|--------|
| **minio/minio** | 2025-02-28 | **DISCONTINUED** | **Switch to Chainguard** |
| postgres | 16-alpine | 17.7-alpine | Upgrade |
| node | 20-alpine | 22-alpine (LTS) | Upgrade |
| python | 3.12-slim | 3.13-slim | Upgrade |
| qdrant | v1.13.2 | v1.17.0 | Update |
| traefik | v3.2 | v3.6.11 | Update (CVE fixes) |
| n8n | 1.82.1 | **2.12.2** | **Major** (breaking) |
| grafana | 11.5.2 | 12.4.1 | Major |
| prometheus | v3.2.1 | v3.10.0 | Update |
| loki | 3.4.2 | 3.6.7 | Update |
| otel-collector | 0.120.0 | 0.147.0 | Update |
| nats | 2.11.3 | 2.12.5 | Update |
| litellm | main-latest | main-latest | **Pin to specific tag** |

---

## Priority Actions

### P0 — Immediate (Security/Broken)
1. Replace `minio/minio` Docker image (discontinued)
2. Replace `python-jose` with `PyJWT` (abandoned, CVEs)
3. Replace `passlib[bcrypt]` with `pwdlib` (broken)
4. Pin `litellm` Docker tag
5. Update `traefik` v3.2 → v3.6.11 (CVE fixes)

### P1 — High (Major Gaps)
6. LangGraph 0.4 → 1.1.0 + LangChain 0.3 → 1.2.x
7. Next.js 15 → 16
8. Tailwind CSS 3 → 4
9. n8n 1.82 → 2.12
10. next-auth v4 → v5 (Auth.js)

### P2 — Medium
11. PostgreSQL 16 → 17, Node 20 → 22, Python 3.12 → 3.13
12. Grafana 11 → 12, Qdrant 1.13 → 1.17, NATS 2.11 → 2.12
13. redis-py 5.x → 7.1.1
14. Consolidate @radix-ui packages
15. lucide-react → 1.0, recharts → 3.8

### P3 — Low
16. Pin all unpinned Python deps
17. Update TypeScript, ESLint after framework upgrades

---

## Packages to Watch

| Package | Status |
|---------|--------|
| python-jose | **Abandoned** (2021) |
| passlib | **Abandoned** (2020) |
| minio (Docker) | **Archived** (Feb 2026) |
| @dnd-kit/* | Stale (~1yr no releases) |
| next-auth v4 | **EOL** |
