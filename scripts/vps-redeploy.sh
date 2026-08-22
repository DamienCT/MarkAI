#!/usr/bin/env bash
set -euo pipefail

# ── MARKAI VPS Redeploy Script ──────────────────────────────────────
# Sanctioned invocation: the GitHub "Deploy" workflow, which SSHes in as
# the "deploy" user and runs the sudoers-whitelisted entry point
# /usr/local/bin/markai-deploy. Verified on the VPS 2026-08-22 (closes N-20):
# that entry point is a sanitizing wrapper — it hex-validates its single
# optional argument, exports it as EXPECTED_SHA, and execs this script with
# NO argv. THIS script still validates its own argv as a redundant layer.
# Manual root runs are break-glass only — see VPS_CONNECTION_GUIDE.md.
#
# Arguments (no flags accepted — anything starting with "-" is rejected):
#   <sha>  optional, at most one: a hex git SHA (7-40 chars). Abort unless
#          HEAD equals it after the pull. CI passes the commit it checked
#          out. Also readable from the EXPECTED_SHA env var.
#
# Environment toggles (break-glass ROOT SHELLS ONLY — sudo's env_reset strips
# these on the sanctioned sudoers path, which is exactly the point: the
# destructive options are unreachable through CI or the deploy user):
#   FORCE_WIPE=true       wipe DB volumes (requires a fresh verified backup)
#   SKIP_BACKUP=true      skip the pre-deploy pg_dump (NOT recommended)
#
# Concurrency: an exclusive NON-BLOCKING flock on /var/tmp/markai-deploy.lock.
# A second deploy while one runs fails immediately and loudly — it must never
# queue silently: two same-morning deploys once double-triggered GPU renders.
# Every attempt appends one line to /var/www/markai/deploys.log
# (ISO timestamp, SHA before -> after, invoking user, outcome).
#
# The WHOLE script body lives inside main(), called on the last line.
# This is load-bearing, not style: Step 1's `git pull` rewrites THIS
# file while bash is still reading it, and an unwrapped script resumes
# at a byte offset inside the NEW file — a 2026-08-20 deploy executed a
# misaligned `down` that way and removed the whole production stack.
# Wrapped, bash parses the entire function before running any of it.

main() {

# Argv contract (closes N-20): at most ONE positional argument, and it must be
# a hex git SHA. Anything starting with "-" is rejected outright, so even if
# /usr/local/bin/markai-deploy is a bare symlink that forwards argv verbatim,
# the sudoers rule cannot smuggle destructive flags through. Destructive
# toggles are env-only (FORCE_WIPE / SKIP_BACKUP, see header) and sudo's
# env_reset strips them on the sanctioned path.
# Empty EXPECTED_SHA means "no pin": break-glass runs deploy whatever main is at.
EXPECTED_SHA="${EXPECTED_SHA:-}"
if [[ "$#" -gt 1 ]]; then
  echo "ERROR: at most one argument is accepted (a git SHA); got $#."
  exit 1
fi
if [[ "$#" -eq 1 ]]; then
  case "$1" in
    -*)
      echo "ERROR: flags are not accepted (got: $1)."
      echo "Pass a git SHA, or use the FORCE_WIPE/SKIP_BACKUP env vars from a root shell."
      exit 1
      ;;
  esac
  if [[ ! "$1" =~ ^[0-9a-f]{7,40}$ ]]; then
    echo "ERROR: argument must be a lowercase hex git SHA (7-40 chars); got: $1"
    exit 1
  fi
  EXPECTED_SHA="$1"
fi
# Env toggles must be exactly "true" to activate; anything else means off.
[[ "${FORCE_WIPE:-}" == true ]] && FORCE_WIPE=true || FORCE_WIPE=false
[[ "${SKIP_BACKUP:-}" == true ]] && SKIP_BACKUP=true || SKIP_BACKUP=false

cd /var/www/markai

echo "=== Step 1: Pull latest code ==="
SHA_BEFORE=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
# Both remotes carry the same main (dual-push convention); prefer ado but fall
# back to origin (GitHub) when its credential has expired.
if ! git pull ado main; then
    echo "WARN: ado pull failed (credential expired?) — falling back to origin"
    git pull origin main
fi
SHA_AFTER=$(git rev-parse HEAD)
echo "  ${SHA_BEFORE} -> ${SHA_AFTER}"

# CI pins the exact commit it checked out. A mismatch means main moved between
# CI checkout and this deploy (or the wrong thing got pulled) — abort NOW,
# while nothing has been built or restarted and the old stack is still up.
if [[ -n "$EXPECTED_SHA" && "$SHA_AFTER" != "$EXPECTED_SHA" ]]; then
  echo "ERROR: HEAD after pull is ${SHA_AFTER}, but EXPECTED_SHA=${EXPECTED_SHA}."
  echo "Nothing was built or restarted; the running stack is untouched."
  echo "Re-run the deploy workflow to ship the current HEAD, or investigate why main moved."
  exit 1
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
  # N-13: NEVER echo the password — this stdout lands verbatim in the CI
  # deploy log. Write it to a root-only file and print only the path.
  TRAEFIK_CRED_FILE="/root/markai-traefik-dashboard.credentials"
  ( umask 077; {
      echo "# Traefik dashboard credentials — generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by vps-redeploy.sh"
      echo "user: admin"
      echo "password: ${TRAEFIK_PASS}"
    } > "$TRAEFIK_CRED_FILE" )
  chmod 600 "$TRAEFIK_CRED_FILE"
  echo "  Added TRAEFIK_DASHBOARD_AUTH (password NOT echoed — stored root-only at ${TRAEFIK_CRED_FILE})"
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
  echo "  SKIP_BACKUP=true detected: skipping database backup (NOT recommended)."
elif ! docker volume inspect markai_pgdata &>/dev/null; then
  echo "  No existing pgdata volume — nothing to back up (first deploy)."
elif ! docker ps --format '{{.Names}}' | grep '^markai-postgres$' >/dev/null; then
  echo "  ERROR: markai-postgres is not running — cannot take a live backup."
  echo "  Start the stack first, or set SKIP_BACKUP=true to deploy without one."
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
    echo "  Set SKIP_BACKUP=true to deploy without a backup (NOT recommended)."
    exit 1
  fi
fi

# FORCE_WIPE is destructive: hard-refuse unless this run produced a verified backup
if [[ "$FORCE_WIPE" == true ]] && docker volume inspect markai_pgdata &>/dev/null && [[ "$BACKUP_OK" != true ]]; then
  echo "  ERROR: FORCE_WIPE refused — no verified backup from this run."
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
  echo "  FORCE_WIPE=true detected: stopping stack and wiping DB volumes..."
  docker compose -f docker-compose.yml -f docker-compose.vps.yml down
  docker volume rm markai_pgdata markai_qdrant_data 2>/dev/null || true
else
  echo "  Using migrations/restart (set FORCE_WIPE=true from a root shell to wipe volumes)."
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

echo "=== Step 9: Drift check (markai-* containers vs expected set) ==="
# The VPS is SHARED with other apps: this check reads ONLY markai-* container
# state and never touches anything outside that prefix. Plain `docker ps` is
# used instead of `docker compose ps --format json` because the JSON shape
# changed across compose v2 releases; container_name is pinned for every
# service, so names are stable. EXPECTED must all be running; TOLERATED are
# the long-running optional containers this deployment actually carries
# (traefik + the observability stack have been up for weeks) — present or
# absent, neither is drift. markai-n8n was removed from this list 2026-08-22
# after the orphan container itself was stopped and removed on the VPS
# (publishing is fully native; its data volume markai_n8n_data is kept as an
# archive) — if a markai-n8n container ever reappears, that IS drift.
EXPECTED_CONTAINERS="markai-backend markai-frontend markai-agents markai-browser-worker markai-notifications markai-postgres markai-qdrant markai-minio markai-valkey markai-nats markai-litellm markai-forge-proxy"
TOLERATED_CONTAINERS="markai-traefik markai-promtail markai-loki markai-grafana markai-prometheus markai-otel-collector"
RUNNING_CONTAINERS=$(docker ps --filter 'name=^markai-' --format '{{.Names}}')
DRIFT=false

for expected in $EXPECTED_CONTAINERS; do
  if ! printf '%s\n' "$RUNNING_CONTAINERS" | grep -Fqx "$expected"; then
    echo "  WARNING: expected container ${expected} is NOT running"
    DRIFT=true
  fi
done

for name in $RUNNING_CONTAINERS; do
  case " ${EXPECTED_CONTAINERS} ${TOLERATED_CONTAINERS} " in
    *" ${name} "*) : ;;
    *) echo "  WARNING: unexpected markai-* container is running: ${name}"; DRIFT=true ;;
  esac
done

UNHEALTHY=$(docker ps --filter 'name=^markai-' --filter 'health=unhealthy' --format '{{.Names}}')
if [[ -n "$UNHEALTHY" ]]; then
  for name in $UNHEALTHY; do
    echo "  WARNING: container reports UNHEALTHY: ${name}"
  done
  DRIFT=true
fi

if [[ "$DRIFT" == false ]]; then
  echo "  OK: all expected markai-* containers running, none unhealthy."
fi

echo "=== Step 10: Health checks (hard gate) ==="
# In-container probe: the backend does not publish 8000 on the host (the
# first live run's host-side curl reported FAILED against a healthy
# container). Retried across ~90s because compose healthchecks need
# start_period + interval x retries before a crash-looping service shows —
# a drift check that runs too early reads "starting" as fine. A backend
# that never answers fails the deploy (CI relies on the exit code).
BACKEND_OK=false
for _try in $(seq 1 9); do
  if docker exec markai-backend python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:8000/health', timeout=5); sys.exit(0 if r.status==200 else 1)" 2>/dev/null; then
    BACKEND_OK=true
    break
  fi
  echo "  backend not answering yet (attempt ${_try}/9) — waiting 10s"
  sleep 10
done
if [[ "$BACKEND_OK" == true ]]; then
  echo "  Backend health: OK"
else
  echo "  WARNING: backend health did not pass within ~90s"
  DRIFT=true
fi

echo ""
echo "=== Step 11: Recent logs (last 20 lines each) ==="
echo "--- backend ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 backend

echo "--- agents ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 agents

echo "--- frontend ---"
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=20 frontend

echo ""
# Drift fails the deploy AFTER status/logs printed above, so the operator (or
# the CI log) has the diagnostics in hand. CI relies on this non-zero exit.
if [[ "$DRIFT" == true ]]; then
  echo "=== DEPLOY FAILED DRIFT CHECK — see Step 9 warnings above ==="
  exit 1
fi

echo "=== Deploy complete ==="

}

# ── Entry point ─────────────────────────────────────────────────────
# Everything below runs BEFORE Step 1's git pull can swap this file, and the
# final `main "$@"; exit "$?"` shares one line so bash never reads another
# line from the (possibly rewritten) file after main returns.

LOCK_FILE="/var/tmp/markai-deploy.lock"
DEPLOY_LOG="/var/www/markai/deploys.log"
SHA_BEFORE="unknown"
SHA_AFTER="unknown"

write_deploy_log() {
  # One line per deploy attempt. Best-effort on purpose: a broken log write
  # must never change the deploy's own exit code.
  printf '%s %s -> %s user=%s outcome=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA_BEFORE" "$SHA_AFTER" \
    "${SUDO_USER:-$(id -un)}" "$1" >> "$DEPLOY_LOG" 2>/dev/null || true
}

on_exit() {
  local code=$?
  if [[ "$code" -eq 0 ]]; then
    write_deploy_log "ok"
  else
    write_deploy_log "failed(exit=${code})"
  fi
}

command -v flock >/dev/null 2>&1 || {
  echo "ERROR: flock not found — refusing to deploy without concurrency protection." >&2
  exit 1
}

# Non-blocking on purpose: a second deploy while one runs must FAIL loudly,
# never queue silently (queued deploys are how the duplicate GPU renders
# happened). The lock lives on the open fd, not the file, so a crashed deploy
# releases it automatically — never delete the lock file to "unstick" things.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "ERROR: another deploy is already running (lock: ${LOCK_FILE})." >&2
  echo "Not queueing behind it. Wait for it to finish, check ${DEPLOY_LOG}, then re-run." >&2
  exit 1
fi

# Trap only once we own the lock, so a lock-refused attempt is not logged as
# a deploy (the deploy it collided with will write its own line).
trap on_exit EXIT

main "$@"; exit "$?"
