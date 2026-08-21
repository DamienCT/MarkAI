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

### Optional — enables the stronger webhook contract

| Variable | Rule |
|---|---|
| `N8N_WEBHOOK_HMAC_SECRET` | When set (backend **and** n8n side), inbound `/api/v1/webhooks/publish-result` callbacks must carry a timestamped HMAC signature and outbound dispatches are signed. Until set, the backend accepts the legacy static-secret-only contract but logs a deprecation warning. Requires the n8n workflow re-import in §4 **before** being set — otherwise callbacks will be rejected and posts recorded `failed`. |

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
- [ ] **`N8N_WEBHOOK_SECRET`**: rotate opportunistically when doing the n8n
      re-import in §4 (both sides must change together).
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

## 4. n8n workflow re-import (HMAC + replay protection)

`docs/n8n-workflows/markai-publish.json` has been updated so the callback
node echoes `X-Webhook-Event-Id` and computes the timestamped HMAC signature.
n8n does **not** pick this up from git — the workflow must be re-imported:

1. In n8n (`https://n8n.srv1191974.hstgr.cloud`), export/back up the current
   `markai-publish` workflow.
2. Set `NODE_FUNCTION_ALLOW_BUILTIN=crypto` in the n8n environment and
   restart n8n **before** activating the re-imported workflow. Its Code
   nodes `require('crypto')` unconditionally — without the allowlist every
   callback crashes inside n8n (the post can still go out but is then
   recorded `failed`).
3. Import the updated `docs/n8n-workflows/markai-publish.json`, re-bind the
   credentials, and activate it (deactivate the old copy).
4. Set the shared secret on the n8n side (env or credential, as the workflow
   expects), then append `N8N_WEBHOOK_HMAC_SECRET=<same value>` to the
   backend `.env` and redeploy.
5. Order matters: **re-import first, set the backend secret second.** The
   backend accepts legacy-format callbacks until the secret is set.
6. **One-callback smoke test (mandatory):** trigger one test publish and
   confirm the backend logs a signed, non-403 `/publish-result` callback for
   it. The exact raw-body shape the HTTP node (n8n typeVersion 4.4) sends
   cannot be proven from the repo — only a live callback proves the HMAC is
   computed over the same bytes the backend verifies. If the callback 403s,
   the HMAC input differs: fix the workflow before trusting any scheduled
   publish.
7. While in n8n: disable execution-data persistence for the publish workflow
   (P0-03 mitigation — execution history retains payloads).

Regardless of HMAC, the backend now enforces monotonic status transitions
(a late `failed` never overwrites `published`; nothing overwrites an operator
cancellation) and replays of the same event id are no-ops.

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
      external `n8n_default` network (other tenants' containers can reach
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
| Full durable HITL resume (`Command(resume)` rebuild) | AG-cluster | Interrupted runs are now safely parked as `paused_for_review` (no chaining, no artifact storage) instead of silently completing; true resume comes with the LangGraph checkpoint rework. |
| Full Alembic baseline regeneration | P0-09 | The repo keeps its documented split: `db/init.sql` is the fresh-install authority; hand-written convergence migrations (`0002`+) move existing DBs. `--autogenerate` is banned (N-16); `env.py` now guards against drops of unmodeled objects. |

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

The OLD worker recorded interrupted strategy runs as `completed`, and those
rows still satisfy `get_latest_strategy` (it filters on `status='completed'`)
— downstream stages can pick up an interrupt payload as if it were a
finished strategy. Identify affected rows by **interrupt-shaped output**:
raw graph state with a top-level `pillars` key, and no strategy artifact
stored for the run (genuine `store_strategy` artifact rows carry
`content_pillars` instead). Inspect, then re-status:

```bash
# Inspect candidates first (output_payload ? 'pillars' is the interrupt-shape
# marker; eyeball each hit before touching it):
ssh markai "docker exec markai-postgres psql -U markai -d markai -c \
  \"SELECT id, brand_id, created_at, left(output_payload::text, 200) \
    FROM agent_runs \
    WHERE agent_type='strategy' AND status='completed' \
      AND output_payload ? 'pillars' \
    ORDER BY created_at DESC;\""
```

For each confirmed interrupt-shaped row, either `UPDATE agent_runs SET
status='failed' WHERE id='<run-id>';` or re-run strategy for the affected
brand (a fresh `completed` run supersedes it — but still re-status the
mislabeled row so it can never become "latest" again).

### Monitoring: `paused_for_review` runs need a human

Interrupted runs are now parked as `status='paused_for_review'`. These
**really occur**, and **nothing auto-resumes them** — the durable-resume
rebuild is deferred (§8); the approval notification is the only signal.
Add this to routine checks:

```bash
ssh markai "docker exec markai-postgres psql -U markai -d markai -c \
  \"SELECT id, agent_type, brand_id, created_at FROM agent_runs \
    WHERE status='paused_for_review' ORDER BY created_at;\""
```

A parked run needs a human decision: act on the approval and re-trigger the
workflow, or mark the run `failed`. Until the resume rebuild lands there is
no third option.
