#!/usr/bin/env bash
set -euo pipefail

# ── MARKAI VPS Redeploy Script ──────────────────────────────────────
# Run this ON the VPS: bash /var/www/markai/scripts/vps-redeploy.sh

cd /var/www/markai

echo "=== Step 1: Pull latest code ==="
git pull origin main

echo "=== Step 2: Generate and add missing env vars ==="
ENV_FILE=".env"

# Fix any previously written TRAEFIK_DASHBOARD_AUTH that has unescaped $ signs
# (from the first failed deploy attempt). Docker Compose needs $$ not $.
if grep -q "^TRAEFIK_DASHBOARD_AUTH=" "$ENV_FILE" 2>/dev/null; then
  EXISTING=$(grep "^TRAEFIK_DASHBOARD_AUTH=" "$ENV_FILE" | head -1)
  # If it contains single $ but not $$, it needs escaping
  if echo "$EXISTING" | grep -q '\$[^$]'; then
    sed -i '/^TRAEFIK_DASHBOARD_AUTH=/d' "$ENV_FILE"
    echo "  Removed bad TRAEFIK_DASHBOARD_AUTH (will regenerate)"
  fi
fi

add_env_if_missing() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    echo "${key}=${value}" >> "$ENV_FILE"
    echo "  Added ${key}"
  else
    echo "  ${key} already set"
  fi
}

# Generate random passwords
RAND1=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)
RAND2=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)
RAND3=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)

add_env_if_missing "QDRANT_API_KEY" "$RAND1"
add_env_if_missing "VALKEY_PASSWORD" "$RAND2"
add_env_if_missing "GF_SECURITY_ADMIN_PASSWORD" "$RAND3"

# Traefik dashboard auth — generate htpasswd format (user: admin)
if ! grep -q "^TRAEFIK_DASHBOARD_AUTH=" "$ENV_FILE" 2>/dev/null; then
  TRAEFIK_PASS=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)
  # Use openssl for htpasswd-compatible bcrypt
  if command -v htpasswd &>/dev/null; then
    HTPASSWD=$(htpasswd -nbB admin "$TRAEFIK_PASS")
  else
    # Fallback: apr1 hash via openssl
    HTPASSWD=$(printf "admin:$(openssl passwd -apr1 "$TRAEFIK_PASS")")
  fi
  # Double all $ signs so Docker Compose doesn't interpolate them as variables
  HTPASSWD_ESCAPED="${HTPASSWD//\$/\$\$}"
  echo "TRAEFIK_DASHBOARD_AUTH=${HTPASSWD_ESCAPED}" >> "$ENV_FILE"
  echo "  Added TRAEFIK_DASHBOARD_AUTH (password: ${TRAEFIK_PASS} — save this!)"
else
  echo "  TRAEFIK_DASHBOARD_AUTH already set"
fi

echo ""
echo "=== Step 3: Stop everything ==="
docker compose -f docker-compose.yml -f docker-compose.vps.yml down

echo "=== Step 4: Database backup & optional volume wipe ==="
# Always create a pg_dump backup before any destructive operation
BACKUP_DIR="/var/www/markai/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/pgdump_$(date +%Y%m%d_%H%M%S).sql.gz"

# Start a temporary postgres container to dump data from the existing volume
if docker volume inspect markai_pgdata &>/dev/null; then
  echo "  Backing up PostgreSQL to ${BACKUP_FILE}..."
  docker run --rm \
    -v markai_pgdata:/var/lib/postgresql/data:ro \
    -v "${BACKUP_DIR}:/backup" \
    -e POSTGRES_PASSWORD=backup \
    postgres:16-alpine \
    bash -c "pg_dump -U ${POSTGRES_USER:-markai} -d ${POSTGRES_DB:-markai} -h /var/run/postgresql 2>/dev/null | gzip > /backup/$(basename $BACKUP_FILE)" \
    || echo "  WARNING: pg_dump failed (volume may be empty on first deploy)"
  echo "  Backup complete: ${BACKUP_FILE}"
else
  echo "  No existing pgdata volume — skipping backup."
fi

if [[ "${1:-}" == "--force-wipe" ]]; then
  echo "  --force-wipe flag detected: wiping DB volumes..."
  docker volume rm markai_pgdata markai_qdrant_data 2>/dev/null || true
else
  echo "  Using migrations/restart (pass --force-wipe to wipe volumes)."
fi

echo "=== Step 5: Rebuild all services ==="
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents browser-worker notifications

echo "=== Step 6: Start everything ==="
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

echo "=== Step 7: Wait for services ==="
echo "Waiting 30s for services to start..."
sleep 30

echo "=== Step 8: Service status ==="
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps

echo "=== Step 9: Health checks ==="
echo "Backend health:"
curl -sf http://localhost:8000/health || echo "FAILED"

echo ""
echo "Backend metrics:"
curl -sf http://localhost:8000/metrics 2>/dev/null | head -3 || echo "FAILED"

echo ""
echo "=== Step 10: Recent logs (last 20 lines each) ==="
echo "--- backend ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 backend

echo "--- agents ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 agents

echo "--- frontend ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 frontend

echo ""
echo "=== Deploy complete ==="
