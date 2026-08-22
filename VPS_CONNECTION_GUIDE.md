# MarkAI VPS — Connection & Interaction Guide

> Hand this file to another Claude Code session.
> Everything needed to interact with the production VPS is below.

---

## TL;DR for the Agent

A persistent SSH alias `markai` is saved at `~/.ssh/config` on the user's PC.
**Use `ssh markai 'command'`** — it auto-resolves to `root@srv1191974.hstgr.cloud`.

If key auth works → no password needed. If it doesn't → read password from the
`SSH_PW` environment variable (user sets this temporarily in `.env`).

```bash
# Preferred (key auth, silent)
ssh markai 'uptime'

# Fallback (password auth via env var, requires sshpass or manual entry)
sshpass -e ssh markai 'uptime'   # with SSHPASS exported from SSH_PW
```

---

## Connection Details

| Property | Value |
|----------|-------|
| **SSH alias** | `markai` (or `markai-vps`) |
| **Host** | `srv1191974.hstgr.cloud` |
| **User** | `root` |
| **Port** | `22` |
| **Key** | `~/.ssh/id_ed25519` (already authorized on VPS) |
| **Password fallback** | `$SSH_PW` env var in project `.env` |

**Firewall:** Port 22 is IP-restricted via Hostinger panel. Your machine's public IP
must be whitelisted before SSH works. Ports 80/443 are open to the world.

---

## First-Time Setup (new machine / fresh agent)

### Step 1: Create SSH config entry

Add to `~/.ssh/config` (create the file if it doesn't exist, mode 600):

```sshconfig
Host markai-vps markai
    HostName srv1191974.hstgr.cloud
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3
    StrictHostKeyChecking accept-new
```

Then `ssh markai 'command'` works from any terminal.

### Step 2: Authenticate

**Option A — SSH key (preferred, silent).** If `~/.ssh/id_ed25519` is already on
the VPS (e.g., copied from a previous session), key auth just works. Test with:
```bash
ssh markai 'uptime'
```

**Option B — Password fallback.** If key auth fails, the user will add the VPS
password to the project `.env` file as `SSH_PW=...`. Load it into your shell and
use `sshpass`:

```bash
# Load the password from .env
export SSHPASS=$(grep '^SSH_PW=' .env | cut -d= -f2-)

# Test
sshpass -e ssh -o StrictHostKeyChecking=accept-new markai 'uptime'
```

If `sshpass` isn't installed:
- **Git Bash / MSYS2 (Windows):** `pacman -S sshpass` (if available) or install via scoop/chocolatey
- **WSL / Linux:** `apt install sshpass` or `dnf install sshpass`
- **macOS:** `brew install hudochenkov/sshpass/sshpass`
- **Fallback:** run `ssh markai` interactively and paste the password from `$SSH_PW`

### Step 3: Install your public key on the VPS (recommended once you have access)

To switch from password to key auth permanently:
```bash
# Get your public key
cat ~/.ssh/id_ed25519.pub

# Append it to authorized_keys on the VPS
sshpass -e ssh markai "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '<paste your pubkey here>' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

After this, `ssh markai` works without a password.

---

## Project Layout on VPS

```
/var/www/markai/              ← Main project directory
├── .env                      ← Production secrets (DO NOT copy off server)
├── docker-compose.yml        ← Base stack (11 services)
├── docker-compose.vps.yml    ← VPS overlay (Traefik labels, no port bindings)
├── scripts/vps-redeploy.sh   ← Deploy script (run via GitHub Action, not by hand)
├── deploys.log               ← One line per deploy attempt (who/what/outcome)
├── backups/                  ← Auto-generated pg_dumps
└── ...

/usr/local/bin/markai-deploy  ← Sudoers-whitelisted deploy entry point (shape unverified — see Deploying)

/docker/n8n/                  ← External n8n + Traefik stack (other tenants' —
└── docker-compose.yml           MarkAI no longer uses n8n; only its Traefik
                                 is shared. Don't modify unless fixing Traefik)
```

---

## Live URLs

| Service | URL | Auth |
|---------|-----|------|
| MarkAI Frontend | https://markai.srv1191974.hstgr.cloud | Azure AD SSO |
| MarkAI API | https://api.markai.srv1191974.hstgr.cloud | JWT (Entra ID) |
| Health check | https://api.markai.srv1191974.hstgr.cloud/health | Public |
| n8n (other tenants — NOT used by MarkAI) | https://n8n.srv1191974.hstgr.cloud | Basic auth |

---

## Common Operations

### Check all services
```bash
ssh markai 'cd /var/www/markai && docker compose -f docker-compose.yml -f docker-compose.vps.yml ps'
```

Expected: 11 services all showing `Up ... (healthy)`:
- markai-backend, markai-frontend, markai-agents
- markai-browser-worker, markai-notifications
- markai-postgres, markai-qdrant, markai-minio
- markai-valkey, markai-nats, markai-litellm

### Deploying — READ THIS BEFORE TOUCHING PRODUCTION

**Manual root deploys are FORBIDDEN** (except break-glass recovery, below).
Ad-hoc `ssh root` runs of the script have taken production down (~15 min: a
mid-run `git pull` rewrote the executing script) and two same-morning manual
deploys double-triggered GPU renders. The sanctioned path:

**GitHub → Actions → "Deploy" → Run workflow** (or ask the orchestrator to
trigger it). The workflow SSHes in as the unprivileged `deploy` user and runs
the sudoers-whitelisted entry point `/usr/local/bin/markai-deploy`. That entry
point is provisioned server-side; whether it is a sanitizing wrapper or a
plain symlink to `scripts/vps-redeploy.sh` is NOT verifiable from this repo
(audit N-20) — the script validates its own argv and stays safe under either
shape. TODO(operator): confirm the actual shape on the VPS
(`ls -l /usr/local/bin/markai-deploy` / `file` / `cat` if a wrapper) and
record the ground truth here. The workflow passes `EXPECTED_SHA` pinned to
the exact commit CI checked out — the deploy aborts, stack untouched, if
`main` moved in between.
A push-to-main auto-deploy also exists in the workflow but **ships disabled**;
it only activates once the `AUTO_DEPLOY` repo variable is set to `true`.

What the deploy does either way: pulls `main` (from `ado`, falling back to
`origin`), backs up the DB, builds before stopping anything, `up -d` recreates
only changed containers, then runs a drift check + health checks. No manual
branch resets, no `build --no-cache`.

#### Render-in-flight rule

**Never deploy while a video render is running.** `up -d` recreates
`markai-agents`, which kills the render mid-flight and drops its queue
(redeploys drop queues — there is no resume). Check first:

```bash
ssh markai "docker exec markai-postgres psql -U markai -d markai -tAc \"select count(*) from agent_runs where status='running'\""
```

Deploy only when that returns `0`, or when the user has explicitly accepted
killing the run in progress.

#### Deploy log

Every deploy that gets past the lock appends one line to
`/var/www/markai/deploys.log`. Two kinds of attempts are NOT in this log:
lock-refused collisions (visible in the refused run's own output/CI log)
and runs killed hard mid-flight (SIGKILL skips the EXIT trap) — so "no
line" does not prove "nobody tried":

```
2026-08-20T09:14:03Z <sha-before> -> <sha-after> user=deploy outcome=ok
```

`outcome=failed(exit=N)` marks aborted runs. Check it before deploying to see
whether someone else just shipped (this is how the duplicate-render morning
would have been caught).

#### Lock file

The script holds a non-blocking exclusive `flock` on
`/var/tmp/markai-deploy.lock`. A second deploy while one runs **fails
immediately** with a clear error — that is by design; do not retry in a loop,
wait for the first to finish. The lock lives on the running process's open
file descriptor, not on the file's existence: a crashed deploy releases it
automatically, so **never delete the lock file** to "fix" anything.

#### Break-glass ONLY: manual deploy

Permitted only when GitHub Actions itself is down (or repo secrets are broken)
and production must be recovered now. Run it under `nohup`, exactly like this:

```bash
ssh markai 'cd /var/www/markai && nohup bash scripts/vps-redeploy.sh < /dev/null >> /var/www/markai/deploy-manual.log 2>&1 & echo "deploy started, pid $!"'
# then watch it:
ssh markai 'tail -f /var/www/markai/deploy-manual.log'
```

Why `nohup` + background: an interactive SSH session that drops mid-deploy
kills the script partway through and leaves the stack half-recreated. Detached
under `nohup`, the deploy survives the disconnect. (The CI path deliberately
does NOT use nohup — the Actions runner holds the session open with keepalives
and needs the foreground exit code.) The render-in-flight check above applies
to break-glass deploys too. Never edit `scripts/vps-redeploy.sh` on the VPS,
and never remove its `main()` wrapper — it is what makes the mid-run
`git pull` self-rewrite safe.

### View logs
```bash
# Specific service
ssh markai 'docker logs markai-backend --tail 50'
ssh markai 'docker logs markai-agents --tail 50'
ssh markai 'docker logs markai-frontend --tail 50'

# Follow logs (Ctrl+C to stop)
ssh markai 'docker logs markai-backend -f'

# All services
ssh markai 'cd /var/www/markai && docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail 20'
```

### Restart a single service
```bash
ssh markai 'cd /var/www/markai && docker compose -f docker-compose.yml -f docker-compose.vps.yml restart backend'
```

### System resources
```bash
ssh markai 'uptime && echo "---" && free -h && echo "---" && docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"'
```

### Database access
```bash
# Interactive psql (use -t flag for TTY)
ssh -t markai 'docker exec -it markai-postgres psql -U markai -d markai'

# One-off query
ssh markai "docker exec markai-postgres psql -U markai -d markai -c 'SELECT count(*) FROM brands;'"
```

### MinIO object storage
```bash
# List buckets
ssh markai 'docker exec markai-backend python3 -c "from app.services.minio_service import get_client; print([b.name for b in get_client().list_buckets()])"'
```

Expected buckets: `content-images`, `brand-assets`, `markai-assets`, `products`

### NATS message publishing (trigger workflows)
```bash
# Trigger brand activation pipeline (research → strategy → planning → content)
ssh markai "docker exec markai-backend python3 -c \"
import asyncio, json, nats as nats_mod
async def trigger():
    from app.config import settings
    nc = await nats_mod.connect('nats://nats:4222', token=settings.NATS_AUTH_TOKEN or None)
    js = nc.jetstream()
    msg = json.dumps({'brand_id': 'BRAND_UUID_HERE', 'trigger': 'activation', 'scope_weeks': 1})
    ack = await js.publish('research.trigger', msg.encode())
    print(f'Published: seq={ack.seq}')
    await nc.close()
asyncio.run(trigger())
\""
```

Replace `BRAND_UUID_HERE` with the actual brand ID. Valid subjects:
`research.trigger`, `strategy.trigger`, `planning.trigger`, `content.generate`

### Database cleanup (dev/testing)
```bash
ssh markai "docker exec markai-postgres psql -U markai -d markai -c '
DELETE FROM approvals;
DELETE FROM content;
DELETE FROM engagement_metrics;
DELETE FROM calendar_items;
DELETE FROM agent_runs;
DELETE FROM campaigns;
'"
```

**WARNING:** This wipes all pipeline data. Brands, users, and products are preserved.

---

## Troubleshooting

### Site returns "can't reach this page" / timeout
1. Check if Traefik is running and has ports bound:
   ```bash
   ssh markai 'docker ps --filter name=traefik && ss -tlnp | grep -E ":80|:443"'
   ```
2. If ports 80/443 not listening, recreate Traefik:
   ```bash
   ssh markai 'cd /docker/n8n && docker compose up -d traefik'
   ```
3. If nginx is holding port 80 (Hostinger default):
   ```bash
   ssh markai 'systemctl stop nginx && systemctl disable nginx'
   ```

### "Network is unreachable" on SSH
Your IP isn't in the Hostinger firewall allowlist. Ask the user to add it via
the Hostinger panel → VPS → Firewall. Rules for reference:

| Action | Protocol | Port | Source |
|--------|----------|------|--------|
| Accept | TCP | 22 | Whitelisted IPs only |
| Accept | TCP | 80 | Any |
| Accept | TCP | 443 | Any |
| Drop | Any | Any | Any |

### Backend 500 errors
```bash
ssh markai 'docker logs markai-backend --tail 100 2>&1 | grep -iE "error|traceback|500"'
```

### Content pipeline stuck
1. Check agents logs:
   ```bash
   ssh markai 'docker logs markai-agents --tail 50'
   ```
2. Check active agent runs:
   ```bash
   ssh markai "docker exec markai-postgres psql -U markai -d markai -c 'SELECT agent_type, status, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 10;'"
   ```

### Image not loading in UI
Product/content images are served via `/api/v1/files/{bucket}/{path}`. Test directly:
```bash
ssh markai 'curl -sf -o /dev/null -w "%{http_code}" "https://api.markai.srv1191974.hstgr.cloud/api/v1/files/content-images/BRAND_ID/ITEM_ID/branded.png"'
```

---

## Related Docs

On the VPS at `/var/www/markai/`:
- `VPS_DEPLOYMENT_GUIDE.md` — Full deployment instructions
- `docs/CONTENT_PIPELINE_SEQUENCE.md` — How the content pipeline works end-to-end
- `SEQUENCE_MAP.html` — Visual pipeline diagram
- `CODEBASE_AUDIT_REPORT.md` — Security/quality audit report

---

## DO NOT

- **Do not deploy manually as root** — the sanctioned path is the GitHub "Deploy" workflow; manual is break-glass only (see the Deploying section)
- **Do not deploy while a render is running** — check `agent_runs` for `status='running'` first (render-in-flight rule above)
- **Do not delete `/var/tmp/markai-deploy.lock`** — a "lock held" error means a deploy is genuinely running; the lock self-releases when it exits
- **Do not commit `.env`** — it has production secrets (Azure AD, OpenAI, Gemini, DB passwords)
- **Do not commit `SSH_PW`** — user adds it temporarily for agent access; remove before commit
- **Do not set `FORCE_WIPE=true`** on the redeploy script unless explicitly asked (wipes DB volumes; env toggle only — the script rejects all flags, including the removed `--force-wipe`). Root shells only: sudo's `env_reset` strips it on the sanctioned CI path, and the script refuses without a fresh verified backup from the same run
- **Do not modify `/docker/n8n/`** unless fixing Traefik — it's an external shared service belonging to other tenants (MarkAI no longer uses n8n; only the Traefik edge in that stack is shared)
- **Do not expose ports** in `docker-compose.vps.yml` — Traefik handles all public routing
- **Do not push to `main`** without testing locally first — there's no staging environment
