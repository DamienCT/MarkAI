# MarkAI Security Containment — Operator Runbook (2026-08-21)

This is the Phase-0 containment runbook for the 2026-08-21 audit
(`MARKAI_COMPREHENSIVE_AUDIT_AND_ROADMAP_2026-08-21.md` and the validation
addendum). It lists the **operator actions** required to activate the
protections shipped in this change set, the credentials that must be rotated,
and the register of items deliberately deferred to a later phase.

Work through the sections in order. Everything here is idempotent — a step
already done can be safely re-verified.

---

## 1. New environment variables (activate before/at next deploy)

The VPS `.env` is **append-only** (see §2 for the procedure). Generate each
secret with `openssl rand -hex 32` unless noted.

### Required in production — backend refuses to start without them

Enforced via the `_REQUIRED_PROD` list in `backend/app/config.py` when
`MARKAI_ENV=production`:

| Variable | Consumed by | Purpose |
|---|---|---|
| `MEDIA_PROXY_TOKEN` | backend **and** frontend (same value) | Grants GET-only access to `/api/v1/files/*` and brand-logo media. The Next.js server uses it to proxy `<img>`/`<video>` requests (`/api/media/...`) with the user's session checked first; anonymous media reads are gone. |
| `NOTIFICATIONS_AUTH_TOKEN` | backend + notifications service | Auth for `/notify` and the per-user HMAC SSE stream tokens. Blank = notifications service refuses **all** requests (fail-closed). |
| `BROWSER_WORKER_API_KEY` | backend/agents + browser-worker | Auth for the Playwright capture service. Blank = browser-worker refuses **all** requests (fail-closed). |

Local-dev escape hatches (`*_ALLOW_ANON=true`, logged loudly at startup) exist
for the two aux services — **never set them on the VPS**.

> **Staging / non-production hosts:** the media-auth gate only fails closed
> under `MARKAI_ENV=production`. Outside production, a blank
> `MEDIA_PROXY_TOKEN` means the media endpoints serve **open** (local-dev
> convenience). Any internet-reachable staging host must therefore either set
> `MARKAI_ENV=production` or set a real `MEDIA_PROXY_TOKEN` — never leave
> both unset on a public host.

### Required conditionally — agents side

| Variable | Rule |
|---|---|
| `VIDEO_FORGE_API_KEY` | Must be non-blank whenever `VIDEO_FORGE_URL` is set; agents production validation fails otherwise. A forge auth error (401/403) now raises a config error instead of silently failing over to paid cloud rendering (N-11). |

### Removed — n8n webhook contract (2026-08-22)

`N8N_WEBHOOK_HMAC_SECRET` — and every other `N8N_*` variable — is no longer
read: n8n was removed and every channel publishes natively from the backend.
See §4 for the remaining operator notes.

### Frontend build contract

Production frontend builds now fail closed (`frontend/next.config.ts`):
`AZURE_AD_TENANT_ID`, `AZURE_AD_CLIENT_ID`, `AZURE_AD_CLIENT_SECRET`, and
`NEXTAUTH_SECRET` (>= 32 chars) must be present or the build exits nonzero.
`NEXT_BUILD_ALLOW_MISSING_RUNTIME_ENV=1` bypasses the check for **image/CI
builds only** (`frontend/Dockerfile` and the CI pipelines set it; the secrets
are injected at container start, where `src/lib/auth.ts` still refuses to run
without them). Never set it on a runtime container.

### Verification

```bash
# On the VPS, after appending the vars and redeploying:
docker logs markai-backend --tail=50        # no _REQUIRED_PROD startup error
docker logs markai-browser-worker --tail=20 # no ALLOW_ANON warning
docker logs markai-notifications --tail=20  # no ALLOW_ANON warning
```

Post-deploy DB verification (migration `0005` swaps the `adaptations` status
CHECK constraint — confirm only the widened one remains):

```bash
ssh markai "docker exec markai-postgres psql -U markai -d markai -c \
  \"SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint \
    WHERE conrelid='adaptations'::regclass AND contype='c';\""
```

Expected: a single `adaptations_status_check` row whose definition includes
`'applied'` and `'rejected'`. Two rows, or one without those values, means
the constraint swap did not converge — do not let learning-loop writes
proceed until it does.

---

## 2. Append-only `.env` procedure

The production `.env` at `/var/www/markai/.env` is the single copy of the
stack's secrets. To avoid corrupting values the deploy script itself manages
(e.g. `TRAEFIK_DASHBOARD_AUTH` with its `$$`-escaping):

1. **Only append** — never rewrite, reorder, or `sed` existing lines:
   ```bash
   ssh root@srv1191974.hstgr.cloud
   echo "MEDIA_PROXY_TOKEN=$(openssl rand -hex 32)" >> /var/www/markai/.env
   ```
2. To *change* an existing value, append a new line with the same key **below**
   the old one (docker compose takes the last occurrence) and note the old
   line with a trailing comment appended as its own line if needed.
3. Recreate the affected containers through the sanctioned deploy path
   (GitHub "Deploy" workflow), or break-glass:
   `cd /var/www/markai && docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d`.
4. **Do not copy `.env` off the server** (P0-13/P0-03 rules).

Deploy-script-generated credentials (Traefik dashboard password etc.) are now
written to root-only files (e.g. `/root/markai-traefik-dashboard.credentials`)
and are **never printed** to the deploy log (N-13).

---

## 3. Credential rotation checklist (do once, soon)

P0-03 / N-01 / N-02: Meta and LinkedIn access tokens have been exposed through
**two** channels — embedded in URLs written to backend stdout/Loki on failed
Graph calls, and returned in cleartext to any viewer/editor via the brand API
(legacy `social_credentials` bypassed the sensitive-key strip). Treat them as
compromised and rotate even though no misuse is confirmed.

- [ ] **Meta page token** (`META_ACCESS_TOKEN` and any per-brand
      `meta_access_token` stored in brand guidelines): invalidate the current
      token in Meta Business settings, issue a new long-lived page token,
      append to `.env`, update the brand records via the UI.
- [ ] **LinkedIn token** (`LINKEDIN_ACCESS_TOKEN` and per-brand
      `linkedin_access_token`): revoke and re-issue via the LinkedIn developer
      app, same propagation.
- [ ] **Teams webhook URL** (`TEAMS_WEBHOOK_URL`): the URL itself is the
      credential and has been persisted/broadcast in failure payloads —
      delete the incoming webhook in Teams and create a fresh one.
- [ ] **Traefik dashboard password**: the previous one was echoed into CI
      deploy logs (N-13). Rotate by deleting the `TRAEFIK_DASHBOARD_AUTH`
      line from `.env` (the one sanctioned exception to append-only — it is
      script-managed) and running a deploy; the script regenerates it into
      `/root/markai-traefik-dashboard.credentials`, root-only, unlogged.
- [x] **`N8N_WEBHOOK_SECRET`**: obsolete — n8n was removed 2026-08-22 (§4);
      the backend no longer reads any `N8N_*` variable, so there is nothing
      to rotate.
- [ ] **`LITELLM_MASTER_KEY`**: lower priority (it was sprayed as a Bearer
      header to an endpoint that needs no auth) — rotate with the next
      routine pass.
- [ ] **frontend.log OAuth authorization codes**: six callback URLs with
      auth codes exist in the retained local `frontend.log`. Codes are
      single-use/short-lived and almost certainly dead — verify no long-lived
      artifacts derive from them, then delete the log (see §6).
- [ ] After rotation, grep recent logs to confirm no token-bearing URLs
      appear anymore (the redaction helper now scrubs `access_token`/`code`/
      `token`-style query params, and httpx request-line logging is
      suppressed).

---

## 4. n8n removed (2026-08-22)

The HMAC re-import procedure that used to live in this section is obsolete:
n8n has been removed from MarkAI entirely. Every channel publishes natively
from the backend (`backend/app/services/publishers/`); the n8n dispatch, its
`/api/v1/webhooks/publish-result` callback, and `docs/n8n-workflows/` are
gone. Remaining operator notes:

- The shared VPS n8n instance at `https://n8n.srv1191974.hstgr.cloud` belongs
  to **other tenants** — MarkAI must never modify, restart, or reconfigure
  it (its Traefik still serves as the shared TLS edge for every tenant).
- You may delete the 'MARKAI - Unified Publisher' workflow from that
  instance at leisure; nothing calls it anymore.
- The `N8N_*` lines in the VPS `.env` are now ignored. Do **not** remove
  them — the `.env` is append-only (§2); leave the lines in place.
- Per-brand channel credentials are entered in the UI (Brand → Channels);
  see `docs/CHANNEL_CREDENTIALS.md`.

Regardless of the dispatch path, the backend still enforces monotonic status
transitions (a late `failed` never overwrites `published`; nothing overwrites
an operator cancellation).

---

## 5. Publishing kill switch

A global switch gates all outbound social publishing — use it during incident
response, credential rotation, or any moment you don't trust the pipeline:

```bash
# Status (admin bearer token required)
curl -s https://api.markai.srv1191974.hstgr.cloud/api/v1/system/publishing-kill-switch \
  -H "Authorization: Bearer <admin-token>"

# Disable all publishing (kill)
curl -s -X PUT https://api.markai.srv1191974.hstgr.cloud/api/v1/system/publishing-kill-switch \
  -H "Authorization: Bearer <admin-token>" -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Re-enable
curl -s -X PUT ... -d '{"enabled": true}'
```

Notes:

- State lives in the `system_flags` table (key `publishing_enabled`). Absent
  row = enabled. Changes are audit-logged.
- Checked at scheduler-sweep start **and** immediately before every external
  dispatch, so flipping it takes effect within one tick.
- Related behavior: items now leave `scheduled` (claim to `publishing`) before
  any dispatch, so duplicate posting on slow callbacks is closed. Items stuck
  in `publishing` >45 min are marked `failed` with note "unreconciled — verify
  on platform before re-scheduling" and are **never auto-retried**: check the
  platform before re-scheduling one by hand.

---

## 6. Forge-proxy network hardening (operator steps)

Per addendum §9 the public Forge endpoint stays published (product
requirement) but must be hardened, not removed:

- [ ] **Key mandatory**: set `VIDEO_FORGE_API_KEY` on both the forge and the
      agents side (§1). The forge must refuse to start serving with a blank
      key — verify after restart that unauthenticated requests to anything
      but `/health` get 401.
- [ ] **Network isolation**: `markai-forge-proxy` must not sit on the shared
      external `n8n_default` network — the legacy n8n stack's Traefik edge
      network, not an n8n dependency (other tenants' containers can reach
      `markai-forge-proxy:9100` directly, bypassing Traefik's rate limit).
      If the compose files in this change set define the dedicated internal
      network, a redeploy applies it; verify with:
      ```bash
      docker inspect markai-forge-proxy --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
      ```
      It must NOT list `n8n_default`. If the network is provisioned outside
      the repo, move it manually and pin the change in the server notes.
- [ ] **Tunnel origin allowlist**: restrict the relay so only the known
      tunnel origin IP(s) can reach the forge port; the relay is path-blind,
      so the key + network are the entire boundary today.
- [ ] **Pending (tracked user actions)**: Tailscale ACL on the tunnel and/or
      mTLS between relay and forge, so an unauthenticated scanner cannot
      touch anything at all. Scanner traffic is already observed in the logs
      — treat this as scheduled work, not hypothetical.

---

## 7. P0-13 data governance — owner decisions required

`docs/build-files/BC-COLUMNS.txt` and `docs/build-files/FABRIC-TABLES.txt`
are raw production diagnostics (BC schema samples across customer/financial
domains; a 256-table Fabric inventory including backup/dev/test/medical
domains). They are git-ignored and were verified untracked, and **they have
not been deleted** — retention and classification is the owner's call, not
this remediation's. Until decided:

- The files stay excluded from git (`.gitignore` now pins their exact paths).
- Exclude the workspace copies from backups, support bundles, screen shares,
  and AI/agent context uploads.
- `docs/build-files/SETUP-REMAINING.md` now carries a sensitivity header;
  the same caution applies to `AUDIT_ARTIFACTS/bc_image_coverage.md` history.

Decisions the owner must record (per P0-13 fix guidance):

1. Keep-and-govern: move both files into an access-controlled catalog with
   owner/purpose/retention/expiry attached, and replace the workspace copies
   with synthetic/redacted fixtures — **or** delete them outright.
2. Whether historical copies (backups, old workspace snapshots) need purging.
3. Whether the local `frontend.log` (7,359 lines, includes OAuth callback
   URLs) is deleted now — recommended, nothing consumes it (§3 last items).

---

## 8. Deferred-items register (accepted, quarter-scale)

Deliberately **not** done in this containment round; tracked here so they are
not mistaken for oversights:

| Item | Audit ref | Why deferred / current mitigation |
|---|---|---|
| Full tenant/authorization model (per-brand scoping of every read) | P0-02 / R-004 | Architecture-level change. Mitigation: role gates remain, media reads now token-gated, guideline strip closes the credential reads. |
| Secret vault migration (references-in-DB, values in vault) | R-003 / P0-03 | Requires vault infrastructure + write-only credential APIs. Mitigation: rotation (§3), strip-at-read, redacted logging. |
| Transactional outbox for dispatch/callback | R-007 | Requires schema + dispatcher rework. Mitigation: claim-before-dispatch, monotonic transitions, replay table, stuck-publishing sweep. |
| Campaign aggregate / consistency boundary | R-023 | Domain remodel. No interim change. |
| ~~Full durable HITL resume (`Command(resume)` rebuild)~~ **DONE 2026-08-22** | AG-cluster / R-022 | Shipped: AsyncPostgresSaver durable checkpoints, `agent.resume.run` authenticated resume (approve/reject + feedback, revision loops capped at 2), worker leases/fencing (migration `0006_hitl_leases`) + heartbeats, "Pending agent reviews" UI on the approvals page. |
| Full Alembic baseline regeneration | P0-09 | The repo keeps its documented split: `db/init.sql` is the fresh-install authority; hand-written convergence migrations (`0002`+) move existing DBs. `--autogenerate` is banned (N-16); `env.py` now guards against drops of unmodeled objects. |

**Shipped 2026-08-22** (not deferrals — recorded here so the register reads
current): Python lockfiles (`requirements.lock` in backend/agents/
browser-worker/notifications, uv-compiled, lockfile-keyed CI caching);
ruff at zero across all four Python trees with CI lint jobs per service;
CI security gates (blocking `pip-audit` per lockfile + blocking gitleaks
secrets scan with a verified-false-positive-only `.gitleaks.toml`) — the
in-repo portion of R-047.

Re-review trigger: any of these deferrals should be revisited before adding a
second worker process, a second tenant, or external users.

---

## 9. Quick reference — what changed in the deploy path itself

- `scripts/vps-redeploy.sh` accepts at most **one** positional argument (a
  hex git SHA) and rejects all flags; destructive toggles are env-only
  (`FORCE_WIPE=true`, `SKIP_BACKUP=true`) and only work from a root shell —
  sudo's `env_reset` strips them on the CI path (N-20).
- Generated credentials are written root-only, never echoed (N-13).
- Schema changes ride `alembic upgrade head` in the backend entrypoint —
  never hand-run `ALTER TABLE` (see `VPS_DEPLOYMENT_GUIDE.md`, "Database
  Schema Changes").

---

## 10. Agent runs — data remediation & monitoring

### One-off data remediation: mislabeled `completed` strategy runs

The OLD worker (pre-2026-08-21) recorded interrupted strategy runs as
`completed`, and those rows still satisfy `get_latest_strategy` (it filters
on `status='completed'`) — downstream stages can pick up an interrupt
payload as if it were a finished strategy. Affected rows carry
**interrupt-shaped output**: the raw graph state with a top-level
`__interrupt__` marker and no `human_approved` key. (Genuine completions
never carry `__interrupt__` and always carry `human_review`'s
`human_approved` — a `pillars` key alone does NOT discriminate; every
legitimate completion has one too.)

This remediation is now scripted — `backend/scripts/remediate_interrupted_runs.py`
(shipped inside the backend image at `/app/scripts/` since 2026-08-22).
Dry-run by default; `--apply` re-statuses the candidates to `failed` with an
explanatory `error_message` while preserving `output_payload` for forensics;
restrict it to eyeballed rows with repeatable `--id <run-id>` flags.
It is idempotent (remediated rows no longer match), and it is a data-only
`UPDATE` — §9's "schema changes ride alembic" rule is untouched.

```bash
ssh markai

# 1. Dry run — prints every candidate row; eyeball each one:
docker exec markai-backend python /app/scripts/remediate_interrupted_runs.py

# 2. Apply — restrict to the rows you confirmed:
docker exec markai-backend python /app/scripts/remediate_interrupted_runs.py \
  --apply --id <run-id> [--id <run-id> ...]
```

The script uses the container's own `DATABASE_URL`; from anywhere else pass
`--dsn postgresql://...`. After applying, re-run strategy for the affected
brand(s) — a fresh approved run becomes "latest" the normal way.

### Monitoring: `paused_for_review` runs need a human decision

Interrupted runs are parked as `status='paused_for_review'` — and since the
2026-08-22 HITL round they are **resumable**: paused runs surface in the
frontend's "Pending agent reviews" panel, where a manager/admin can
**Approve** or **Reject** (reject requires feedback). The decision is
audit-logged, published over NATS (`agent.resume.run`), and the worker
resumes the graph from its durable checkpoint — approved runs finalize and
chain as normal, rejected runs regenerate with the feedback in context and
re-pause for another review (bounded: the run fails after repeated
rejections). The old "nothing can resume them" caveat no longer applies.

The psql check stays useful as a **backstop** for runs sitting paused longer
than expected (nobody has decided yet, or a resume request was lost in
transit — either way the run simply stays `paused_for_review`, and clicking
Approve/Reject again re-publishes the request):

```bash
ssh markai "docker exec markai-postgres psql -U markai -d markai -c \
  \"SELECT id, agent_type, brand_id, created_at FROM agent_runs \
    WHERE status='paused_for_review' ORDER BY created_at;\""
```

A run listed here for more than a working day needs a decision in the UI —
or, if the run is obsolete, mark it `failed` by hand.
