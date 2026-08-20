#!/usr/bin/env bash
set -euo pipefail

# ── MARKAI Nightly Backup Script ────────────────────────────────────
# Run this ON the VPS from the root crontab, e.g.:
#   30 3 * * * bash /var/www/markai/scripts/nightly-backup.sh >> /var/log/markai-backup.log 2>&1
#
# What it does:
#   1. pg_dump from the running markai-postgres container, gzipped + verified
#   2. Rotation: keeps the newest 14 dumps in /var/www/markai/backups
#   3. Mirrors MinIO object storage to backups/minio (only if `mc` is installed)
#   4. Offsite sync via rclone (only if a remote named `offsite:` is configured)
#
# Check mode (for cron/monitoring — takes no backup):
#   bash /var/www/markai/scripts/nightly-backup.sh check
#   Exits 0 if the newest dump is fresher than 26h, non-zero + ALERT otherwise.

cd /var/www/markai

BACKUP_DIR="/var/www/markai/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/pgdump_$(date +%Y%m%d_%H%M%S).sql.gz"

# ── Backup-age check helper ─────────────────────────────────────────
# Invoked as `nightly-backup.sh check` — must branch BEFORE the backup
# steps below run, so the dispatch lives up here.
check_backup_age() {
  local newest age_hours
  newest=$(ls -1t "${BACKUP_DIR}"/pgdump_*.sql.gz 2>/dev/null | head -1 || true)
  if [[ -z "$newest" ]]; then
    echo "ALERT: no pgdump backups found in ${BACKUP_DIR}"
    return 1
  fi
  age_hours=$(( ($(date +%s) - $(stat -c %Y "$newest")) / 3600 ))
  if (( age_hours >= 26 )); then
    echo "ALERT: newest backup ${newest} is ${age_hours}h old (threshold: 26h)"
    return 1
  fi
  echo "OK: newest backup ${newest} is ${age_hours}h old"
}

if [[ "${1:-}" == "check" ]]; then
  if check_backup_age; then
    exit 0
  else
    exit 1
  fi
fi

echo "=== Nightly backup started: $(date '+%Y-%m-%d %H:%M:%S') ==="

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

echo "=== Step 1: PostgreSQL dump ==="
if ! docker ps --format '{{.Names}}' | grep '^markai-postgres$' >/dev/null; then
  echo "  ERROR: markai-postgres is not running — cannot take a backup."
  exit 1
fi

echo "  Backing up PostgreSQL to ${BACKUP_FILE}..."
if docker exec markai-postgres \
     sh -c 'pg_dump -U "${POSTGRES_USER:-markai}" -d "${POSTGRES_DB:-markai}"' \
     | gzip > "$BACKUP_FILE" \
   && verify_backup "$BACKUP_FILE"; then
  echo "  Backup verified: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
else
  rm -f "$BACKUP_FILE"
  echo "  ERROR: backup failed verification — removed partial file."
  exit 1
fi

echo "=== Step 2: Rotate old backups (keep newest 14) ==="
ls -1t "${BACKUP_DIR}"/pgdump_*.sql.gz | tail -n +15 | xargs -r rm -f
echo "  $(ls -1 "${BACKUP_DIR}"/pgdump_*.sql.gz | wc -l) dump(s) on disk."

echo "=== Step 3: MinIO mirror ==="
if command -v mc &>/dev/null; then
  ENV_FILE="/var/www/markai/.env"
  get_env() { grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }
  MINIO_ACCESS=$(get_env MINIO_ACCESS_KEY)
  MINIO_ACCESS=${MINIO_ACCESS:-markai-minio}
  MINIO_SECRET=$(get_env MINIO_SECRET_KEY)
  # MinIO has no host port binding on the VPS — reach it via its container IP
  MINIO_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' markai-minio 2>/dev/null || true)
  if [[ -n "$MINIO_SECRET" && -n "$MINIO_IP" ]]; then
    echo "  Mirroring MinIO (${MINIO_IP}:9000) to ${BACKUP_DIR}/minio..."
    mkdir -p "${BACKUP_DIR}/minio"
    mc alias set markai-backup "http://${MINIO_IP}:9000" "$MINIO_ACCESS" "$MINIO_SECRET" >/dev/null
    mc mirror --overwrite --quiet markai-backup "${BACKUP_DIR}/minio"
    echo "  MinIO mirror complete."
  else
    echo "  WARNING: MinIO container or credentials not found — skipping mirror."
  fi
else
  echo "  mc not installed — skipping MinIO mirror (install: https://min.io/docs/minio/linux/reference/minio-mc.html)."
fi

echo "=== Step 4: Offsite sync (rclone) ==="
if command -v rclone &>/dev/null && rclone listremotes 2>/dev/null | grep -q '^offsite:$'; then
  echo "  Copying ${BACKUP_FILE} to offsite:markai-backups/pgdump..."
  rclone copy "$BACKUP_FILE" offsite:markai-backups/pgdump
  if [[ -d "${BACKUP_DIR}/minio" ]]; then
    echo "  Syncing MinIO mirror to offsite:markai-backups/minio..."
    rclone sync "${BACKUP_DIR}/minio" offsite:markai-backups/minio
  fi
  echo "  Offsite sync complete."
else
  echo "  Offsite unconfigured — create an rclone remote named 'offsite' to enable it."
fi

echo "=== Nightly backup complete: $(date '+%Y-%m-%d %H:%M:%S') ==="
