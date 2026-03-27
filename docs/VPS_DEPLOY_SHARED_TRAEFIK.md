# MARKAI VPS Deployment — Shared Traefik

Deploy MARKAI to a VPS that already has Traefik running on ports 80/443.

## Architecture

```
Internet
   │
   ▼
VPS Traefik (existing, owns :80/:443)
   │
   ├── markai.srv1191974.hstgr.cloud       → markai-frontend:3000
   └── api.markai.srv1191974.hstgr.cloud   → markai-backend:8000
   │
   ▼ (Docker network: n8n_default)
   │
MARKAI Internal Network (markai-net) — no ports exposed to host
   ├── postgres:5432
   ├── qdrant:6333
   ├── minio:9000
   ├── valkey:6379
   ├── nats:4222
   ├── litellm:4000
   ├── browser-worker:8001
   ├── notifications:8002
   └── agents (no port — NATS consumer)
```

**Key design:** MARKAI does NOT bind any host ports. Everything communicates over the internal `markai-net` Docker network. Only frontend and backend are connected to the external `n8n_default` network so the VPS Traefik can route to them. MARKAI uses the existing VPS n8n instance via public URL/env configuration.

## Prerequisites

1. VPS with Docker and Docker Compose v2 installed
2. Existing Traefik reverse proxy running on the VPS (owns ports 80/443)
3. Existing VPS Traefik is attached to the `n8n_default` Docker network and uses the `mytlschallenge` cert resolver
4. DNS records pointing to your VPS IP:
   - `markai.srv1191974.hstgr.cloud` → VPS IP
   - `api.markai.srv1191974.hstgr.cloud` → VPS IP

## Step 1: Create the external network (if it doesn't exist)

```bash
docker network inspect n8n_default --format '{{range .Containers}}{{.Name}} {{end}}'
```
You should see your VPS Traefik container listed.

## Step 2: Clone and configure

```bash
cd /var/www
git clone https://github.com/DamienCT/MarkAI.git markai
cd markai

# Create .env from the VPS template
cp .env.vps.example .env
```

Edit `.env` and fill in ALL values. Pay special attention to:

| Variable | What to set |
|----------|-------------|
| `SECRET_KEY` | `openssl rand -hex 32` |
| `NEXTAUTH_SECRET` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |
| `MINIO_SECRET_KEY` | `openssl rand -hex 24` |
| `LITELLM_MASTER_KEY` | `openssl rand -hex 24` |
| `N8N_WEBHOOK_SECRET` | `openssl rand -hex 32` |
| `AZURE_AD_*` | From your Azure portal app registration |
| `OPENAI_API_KEY` | From OpenAI dashboard |
| `GEMINI_API_KEY` | From Google AI Studio |

Quick secret generation:
```bash
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "NEXTAUTH_SECRET=$(openssl rand -hex 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
echo "MINIO_SECRET_KEY=$(openssl rand -hex 24)"
echo "LITELLM_MASTER_KEY=$(openssl rand -hex 24)"
echo "N8N_WEBHOOK_SECRET=$(openssl rand -hex 32)"
```

## Step 3: Build and deploy

```bash
# Build all images
docker compose -f docker-compose.yml -f docker-compose.vps.yml build

# Start everything
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

The VPS Traefik will automatically:
- Detect the new containers via Docker labels on `n8n_default`
- Obtain TLS certificates via the existing `mytlschallenge` resolver
- Route traffic to the correct services

## Step 4: Verify

```bash
# Check all containers are running
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps

# Check health
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps --format "table {{.Name}}\t{{.Status}}"

# Test backend
curl -s https://api.markai.srv1191974.hstgr.cloud/health

# Test frontend
curl -s -o /dev/null -w "%{http_code}" https://markai.srv1191974.hstgr.cloud/

# Check logs if something is wrong
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs backend --tail 50
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs frontend --tail 50
```

## Port Conflict Prevention

| Service | Host port | Status |
|---------|-----------|--------|
| Traefik (bundled) | 80, 443, 8080 | **Disabled** (profiles: disabled) |
| PostgreSQL | 5432, 5433 | **None** (internal only) |
| Redis/Valkey | 6379, 6381 | **None** (internal only) |
| MinIO | 9000, 9001 | **None** (internal only) |
| n8n | existing VPS service | **Reused** (MARKAI integrates with existing VPS n8n) |
| Backend | 8000 | **None** (internal only, Traefik routes) |
| Frontend | 3000 | **None** (internal only, Traefik routes) |
| All other services | * | **None** (internal only) |

**Zero host port bindings.** No conflicts possible with existing VPS services.

## Useful Commands

```bash
# Shortcut: create an alias
alias mdc='docker compose -f docker-compose.yml -f docker-compose.vps.yml'

# Then use:
mdc up -d
mdc ps
mdc logs -f backend
mdc restart backend
mdc down

# Enable observability stack (optional):
mdc --profile observability up -d

# View database (from inside the network):
docker exec -it markai-postgres psql -U markai -d markai
```

## Rollback

```bash
# Stop everything
docker compose -f docker-compose.yml -f docker-compose.vps.yml down

# Data is preserved in Docker volumes (pgdata, minio_data, etc.)
# To roll back to a previous version:
git checkout <previous-commit>
docker compose -f docker-compose.yml -f docker-compose.vps.yml build
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

# Nuclear option — remove everything including data:
docker compose -f docker-compose.yml -f docker-compose.vps.yml down -v
```

## Updating

```bash
cd /var/www/markai
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.vps.yml build
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

## Troubleshooting

**Traefik not routing to MARKAI containers:**
```bash
# Check containers are on n8n_default network
docker network inspect n8n_default | grep markai

# Check Traefik can see the labels
docker inspect markai-frontend --format '{{json .Config.Labels}}' | jq
```

**Backend returns 500:**
```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs backend --tail 100
# Common cause: missing env vars or DB not ready
```

**Frontend shows blank page:**
```bash
# NEXT_PUBLIC_API_URL must be the public API URL, not internal hostname
grep NEXT_PUBLIC_API_URL .env
# Must be: https://api.markai.srv1191974.hstgr.cloud
```

**TLS certificate not issued:**
- Check DNS A records point to VPS IP
- Check VPS Traefik logs: `docker logs <traefik-container-name> --tail 50`
- Ensure port 80 is accessible for ACME HTTP challenge
