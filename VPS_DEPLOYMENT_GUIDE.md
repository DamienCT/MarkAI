# MARKAI VPS Deployment Guide

> **Self-contained deployment instructions.** Everything needed to deploy
> MarkAI to the production VPS is in this document. No additional credentials
> or configuration required — the `.env` file is already on the server.

<!-- The redeploy script now pulls from the `ado` remote (Azure DevOps),
     not `origin` (GitHub mirror). VPS auths via /root/.git-credentials-ado. -->


---

## Server Details

| Property | Value |
|----------|-------|
| **Host** | `srv1191974.hstgr.cloud` |
| **SSH** | `root@srv1191974.hstgr.cloud` (key-based auth, no password) |
| **OS** | Ubuntu / Debian (Docker pre-installed) |
| **Project path** | `/var/www/markai` |
| **Git remote** | Azure DevOps: `https://dev.azure.com/Chemtech-IT/Information%20Technology/_git/MARK%20AI` |
| **Branch** | `main` |

## Live URLs

| Service | URL |
|---------|-----|
| **Frontend** | `https://markai.srv1191974.hstgr.cloud` |
| **Backend API** | `https://api.markai.srv1191974.hstgr.cloud` |
| **Health check** | `https://api.markai.srv1191974.hstgr.cloud/health` |

---

## Quick Deploy (Standard)

The sanctioned deploy path is the GitHub **"Deploy" workflow** (Actions →
Deploy → Run workflow), which runs `scripts/vps-redeploy.sh` on the VPS
pinned to the exact commit CI checked out — see the CI/CD section below.

Break-glass alternative (script broken in CI, GitHub down): SSH in as root
and run the same script directly:

```bash
ssh root@srv1191974.hstgr.cloud
cd /var/www/markai
bash scripts/vps-redeploy.sh
```

The script does everything automatically:
1. Pulls latest `main` (from `ado`, falling back to `origin`)
2. Generates any missing env vars (random passwords for new services —
   generated credentials are written to root-only files such as
   `/root/markai-traefik-dashboard.credentials`, never printed to the log)
3. Backs up PostgreSQL before any changes
4. Rebuilds changed Docker images (backend, frontend, agents, browser-worker, notifications) — the old stack keeps running if a build fails
5. Recreates only changed containers via `up -d` (postgres/nats/minio keep running)
6. Waits 30s then runs health checks
7. Shows service status and recent logs

**This script is the only sanctioned deploy path.** Never deploy by resetting
to a feature branch or with `build --no-cache`.

**Expected result:** All services show `Up ... (healthy)`, health endpoint returns `{"status":"ok"}`.

---

## Manual Deploy (Step by Step)

**Reference only — for debugging when the script itself is broken.** These
steps skip the pre-deploy database backup the script takes; prefer
`bash scripts/vps-redeploy.sh` in every normal case.

```bash
ssh root@srv1191974.hstgr.cloud
cd /var/www/markai

# 1. Pull code
git pull origin main

# 2. Rebuild only changed services
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents browser-worker notifications

# 3. Restart (zero-downtime — recreates changed containers only)
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

# 4. Verify
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
curl -sf https://api.markai.srv1191974.hstgr.cloud/health
```

---

## Database Schema Changes

**Never hand-run `ALTER TABLE` against the production database.** Alembic IS
in use: the backend container's entrypoint (`backend/docker-entrypoint.sh`)
runs `alembic upgrade head` automatically on every start, so schema changes
land as part of the normal deploy — no manual SQL step exists. Hand-run DDL
is exactly the drift that migration `0002` had to be written to repair.

How schema changes ship:

1. `db/init.sql` is the **fresh-install authority** — a new empty database is
   built from it, not from the migration chain.
2. Every change to `init.sql` is mirrored by a **hand-written convergence
   migration** in `backend/alembic/versions/` (idempotent `IF NOT EXISTS` /
   guarded `DO $$` blocks, in the style of `0002`–`0004`) so an existing
   prod DB converges to the same shape on the next deploy.
3. Never use `alembic revision --autogenerate`: `env.py`'s metadata is
   incomplete (e.g. `brand_model_profiles` has no ORM model) and autogenerate
   would emit `DROP TABLE` for everything it can't see.

To verify a migration applied after a deploy:

```bash
docker exec markai-postgres psql -U markai -d markai -c "SELECT version_num FROM alembic_version;"
docker logs markai-backend 2>&1 | grep -i alembic | tail -5
```

---

## Full Wipe Deploy (Nuclear Option)

**WARNING: Destroys all data (brands, content, products, users).**
Only use for a fresh start. The script accepts no flags (anything starting
with `-` is rejected so the sudoers deploy path can never forward destructive
options) — the wipe is an environment toggle, usable only from a root shell:

```bash
FORCE_WIPE=true bash scripts/vps-redeploy.sh
```

This wipes the PostgreSQL and Qdrant volumes. A verified backup is created
first at `/var/www/markai/backups/` — the script hard-refuses the wipe
without one (`SKIP_BACKUP=true` does not override that refusal).

---

## Architecture

```
Internet
  |
  v
Traefik (VPS-level, shared with n8n)
  |
  +-- markai.srv1191974.hstgr.cloud --> frontend:3000  (Next.js)
  +-- api.markai.srv1191974.hstgr.cloud --> backend:8000  (FastAPI)
  |
  Internal Docker network (markai-net):
    backend:8000     FastAPI REST API + scheduler
    frontend:3000    Next.js SSR + static
    agents           LangGraph AI worker (NATS consumer)
    browser-worker:8001  Playwright headless browser
    notifications:8002   SSE + Teams webhooks
    postgres:5432    PostgreSQL 16
    nats:4222        NATS JetStream message broker
    litellm:4000     LLM gateway proxy
    minio:9000       S3-compatible object storage
    valkey:6379      Redis-compatible cache
    qdrant:6333      Vector database
```

**11 services** total. Traefik and n8n are external (shared VPS services, not managed by this stack).

---

## Environment Configuration

The `.env` file is already on the VPS at `/var/www/markai/.env` with all production
secrets configured. **Do not copy it off the server.**

Key env vars:
- `MARKAI_ENV=production` — enables strict credential validation
- `MARKAI_DOMAIN=markai.srv1191974.hstgr.cloud` — used by Traefik labels
- Azure AD SSO credentials (tenant, client ID/secret)
- OpenAI + Gemini API keys (for content generation)
- Microsoft Fabric credentials (for Business Central product sync)
- Database, MinIO, NATS, Valkey passwords
- n8n webhook secret (for social publishing callbacks)
- Inter-service auth tokens (NATS, browser-worker, notifications)

If you need to add a new env var:
```bash
ssh root@srv1191974.hstgr.cloud
echo "NEW_VAR=value" >> /var/www/markai/.env
```

---

## Troubleshooting

### Check service status
```bash
cd /var/www/markai
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
```

### View logs
```bash
# All services
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=50

# Specific service
docker logs markai-backend --tail=50
docker logs markai-agents --tail=50
docker logs markai-frontend --tail=50
```

### Restart a single service
```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml restart backend
```

### Check memory usage
```bash
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"
```

### Database access
```bash
docker exec -it markai-postgres psql -U markai -d markai
```

### MinIO object storage
```bash
# List buckets
docker exec markai-backend python3 -c "
from app.services.minio_service import get_client
print([b.name for b in get_client().list_buckets()])
"
```

### Trigger content pipeline manually
```bash
docker exec markai-backend python3 -c "
import asyncio, json, nats as nats_mod
async def trigger():
    from app.config import settings
    nc = await nats_mod.connect('nats://nats:4222', token=settings.NATS_AUTH_TOKEN or None)
    js = nc.jetstream()
    msg = json.dumps({'brand_id': 'BRAND_UUID_HERE', 'trigger': 'activation', 'scope_weeks': 1})
    await js.publish('research.trigger', msg.encode())
    await nc.close()
    print('Triggered')
asyncio.run(trigger())
"
```

---

## Backup & Recovery

Backups are created automatically by the deploy script at `/var/www/markai/backups/`.

Manual backup:
```bash
docker exec markai-postgres pg_dump -U markai -d markai | gzip > /var/www/markai/backups/manual_$(date +%Y%m%d).sql.gz
```

Restore:
```bash
gunzip -c /var/www/markai/backups/pgdump_YYYYMMDD_HHMMSS.sql.gz | docker exec -i markai-postgres psql -U markai -d markai
```

---

## Docker Compose Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base stack definition (all 16 services) |
| `docker-compose.vps.yml` | VPS overlay: disables bundled Traefik, adds Traefik labels, connects to external network, disables observability stack |

Always use both:
```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml <command>
```

---

## CI/CD

GitHub Actions runs on push to `main`:
- Backend lint (Ruff)
- Frontend lint (ESLint + TypeScript)
- Backend tests (pytest)
- Agents tests (pytest)
- Frontend build check

Deployment runs through the "Deploy" workflow (`.github/workflows/deploy.yml`):
manual `Run workflow` dispatch always works; push-to-main auto-deploy is
gated behind the `AUTO_DEPLOY` repo variable. The workflow SSHes in as the
unprivileged `deploy` user and runs the sudoers-whitelisted
`/usr/local/bin/markai-deploy <sha>`, which reaches `scripts/vps-redeploy.sh`.
Remember: a deploy recreates `markai-agents` and kills any running video render.
