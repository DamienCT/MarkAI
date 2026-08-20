#!/usr/bin/env bash
set -euo pipefail

# ── MARKAI VPS Redeploy Script ──────────────────────────────────────
# Run this ON the VPS: bash /var/www/markai/scripts/vps-redeploy.sh
# Flags:
#   --force-wipe   wipe DB volumes (requires a fresh verified backup)
#   --skip-backup  skip the pre-deploy pg_dump (NOT recommended)
#
# The WHOLE script body lives inside main(), called on the last line.
# This is load-bearing, not style: Step 1's `git pull` rewrites THIS
# file while bash is still reading it, and an unwrapped script resumes
# at a byte offset inside the NEW file — a 2026-08-20 deploy executed a
# misaligned `down` that way and removed the whole production stack.
# Wrapped, bash parses the entire function before running any of it.

main() {

cd /var/www/markai

FORCE_WIPE=false
SKIP_BACKUP=false
for arg in "$@"; do
  case "$arg" in
    --force-wipe)  FORCE_WIPE=true ;;
    --skip-backup) SKIP_BACKUP=true ;;
    *) echo "Unknown flag: ${arg} (supported: --force-wipe, --skip-backup)"; exit 1 ;;
  esac
done

echo "=== Step 1: Pull latest code ==="
# Both remotes carry the same main (dual-push convention); prefer ado but fall
# back to origin (GitHub) when its credential has expired.
if ! git pull ado main; then
    echo "WARN: ado pull failed (credential expired?) — falling back to origin"
    git pull origin main
fi

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
echo "=== Step 3: Database backup (while the stack is still running) ==="
# Always create a verified pg_dump backup BEFORE any destructive operation.
# The dump is taken from the live postgres container — it must be running.
BACKUP_DIR="/var/www/markai/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/pgdump_$(date +%Y%m%d_%H%M%S).sql.gz"
BACKUP_OK=false

verify_backup() {
  # Valid gzip + non-empty + pg_dump completion marker at the end of the dump
  local file="$1"
  gzip -t "$file" 2>/dev/null || return 1
  local bytes
  bytes=$(gzip -dc "$file" 2>/dev/null | wc -c) || return 1
  [[ "$bytes" -gt 0 ]] || return 1
  local tail_lines
  tail_lines=$(gzip -dc "$file" 2>/dev/null | tail -n 5) || return 1
  [[ "$tail_lines" == *"PostgreSQL database dump complete"* ]] || return 1
}

if [[ "$SKIP_BACKUP" == true ]]; then
  echo "  --skip-backup flag detected: skipping database backup (NOT recommended)."
elif ! docker volume inspect markai_pgdata &>/dev/null; then
  echo "  No existing pgdata volume — nothing to back up (first deploy)."
elif ! docker ps --format '{{.Names}}' | grep '^markai-postgres$' >/dev/null; then
  echo "  ERROR: markai-postgres is not running — cannot take a live backup."
  echo "  Start the stack first, or pass --skip-backup to deploy without one."
  exit 1
else
  echo "  Backing up PostgreSQL to ${BACKUP_FILE}..."
  if docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T postgres \
       sh -c 'pg_dump -U "${POSTGRES_USER:-markai}" -d "${POSTGRES_DB:-markai}"' \
       | gzip > "$BACKUP_FILE" \
     && verify_backup "$BACKUP_FILE"; then
    BACKUP_OK=true
    echo "  Backup verified: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
    # Rotation: keep the newest 14 backups, delete older ones
    ls -1t "${BACKUP_DIR}"/pgdump_*.sql.gz | tail -n +15 | xargs -r rm -f
  else
    rm -f "$BACKUP_FILE"
    echo "  ERROR: backup failed verification — aborting deploy (nothing was stopped or wiped)."
    echo "  Pass --skip-backup to deploy without a backup (NOT recommended)."
    exit 1
  fi
fi

# --force-wipe is destructive: hard-refuse unless this run produced a verified backup
if [[ "$FORCE_WIPE" == true ]] && docker volume inspect markai_pgdata &>/dev/null && [[ "$BACKUP_OK" != true ]]; then
  echo "  ERROR: --force-wipe refused — no verified backup from this run."
  echo "  Wiping volumes without a fresh verified backup would lose data permanently."
  exit 1
fi

echo ""
echo "=== Step 4: Rebuild changed services (stack stays up) ==="
# Build BEFORE stopping anything: under set -e a failed build aborts the
# deploy right here with the old stack still running, instead of offline.
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents browser-worker notifications

echo "=== Step 5: Optional volume wipe ==="
if [[ "$FORCE_WIPE" == true ]]; then
  echo "  --force-wipe flag detected: stopping stack and wiping DB volumes..."
  docker compose -f docker-compose.yml -f docker-compose.vps.yml down
  docker volume rm markai_pgdata markai_qdrant_data 2>/dev/null || true
else
  echo "  Using migrations/restart (pass --force-wipe to wipe volumes)."
fi

echo "=== Step 6: Start/recreate changed containers ==="
# 'up -d' recreates only containers whose image or config changed —
# postgres/nats/minio keep running instead of restarting on every deploy.
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

}

main "$@"
