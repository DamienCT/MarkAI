# MarkAI Audit — Independent Validation & Enhancement Addendum

**Companion to** `MARKAI_COMPREHENSIVE_AUDIT_AND_ROADMAP_2026-08-21.md`
**Method:** 12 independent verification agents re-read the cited code (no trust in the report's own evidence), plus adversarial recheck of every REFUTED verdict, plus locally-executed checks (`npm audit`, `npm run lint`, `npm run build` with config unset, `ruff`, `ffmpeg ebur128`, a live `langgraph` interrupt probe). 461 tool calls total. Findings below are keyed to the report's IDs.

**Headline:** the report is substantially correct and unusually careful. Every P0 kernel I tested holds up. The enhancements here are (a) **corrections** where the report overstated a mechanism or picked the wrong failure vector, (b) **priority recalibration** — several "P0 stop-ship" items are gated by the current single-process/single-worker/internal-only topology and are *latent*, not live, while a few things the report filed as secondary are the ones actually leaking secrets today, and (c) **~30 new code-evidenced defects** the report missed, several higher-impact than items it did flag.

---

## 1. Verdict on the report's own P0/P1 claims

| Report ID | Claim (short) | Verdict | Note |
|---|---|---|---|
| P0-01 / AG-01 | LangGraph interrupt bypassed, no resume, MemorySaver | **CONFIRMED** | Proven empirically — see §2.1 |
| P0-06 / AG-02 | Learning loop structurally nonfunctional | **CONFIRMED** (worse) | Even a tier-filter fix can't revive it — see §2.2 |
| P0-04 / BE-03/11 | Publish race, no idempotency, no leader election | **CONFIRMED** | Latent, not live single-process — see §3 |
| P0-04 (4) | Late "pending" webhook regresses "published" | **PARTIAL** | That exact vector is impossible (422-rejected); the real regressor is a replayed **failed** callback — see §2.3 |
| P0-02 / BE-01 | No tenant/brand authz model | **CONFIRMED** | Read side looser than reported |
| P0-08 / BE-05 | Media proxy lacks ownership enforcement | **CONFIRMED** (worse) | `/files` is fully **unauthenticated**, not just under-authorized |
| P0-08 | SVG/data-URI active content | **PARTIAL** | Upload path *blocks* SVG; the hole is the server-side logo **fetch** path + no CSP — see §2.4 |
| P0-03 / BE-02 | Social creds plaintext, returned by API, in n8n payloads | **PARTIAL** | Storage + n8n = true; "returned by brand API" is overstated (a strip layer predates the audit) — but it's **bypassed for legacy creds** — see §4 |
| P0-03 | `frontend.log` holds 6 OAuth codes | **CONFIRMED** | They're Entra *login* codes, single-use, dead since March — hygiene, not exposure |
| P0-05 | Webhook static secret, no HMAC, **no timestamp**, replayable | **PARTIAL** | A ±5-min timestamp check *exists* but is dormant (only runs if caller sends the header, and n8n never does). Conclusion holds; "no timestamp" is literally wrong |
| P0-07 | Browser-worker SSRF, substring domains, fail-open auth | **CONFIRMED** (worse) | It's full-read SSRF (returns 50k chars / screenshots internal targets), and the shipped VPS template disables its auth — see §4 |
| P0-07 | Notifications unauth `/notify` + SSE IDOR | **CONFIRMED** | Real in code, but service is internal-only **and has zero live callers** — dormant |
| P0-09 / BE-07 | Alembic baseline empty, fresh DB stamped not migrated | **CONFIRMED** | `alembic upgrade head` on an empty DB doesn't under-build — it **crashes**. Already drifted once in 48h — see §5 |
| P0-10 | Quality gates fail open into review | **CONFIRMED** | Deliberate "record don't block"; nothing reads the flags — see §6 |
| P0-11 / BE-06 | Audit hard-deletable, no kill switch, global shutdown-fail | **CONFIRMED / PARTIAL** | Brand-deactivate *does* cancel DB rows (report overstates); but nothing signals the running worker — see §7 |
| P0-12 / FE-01/03/04 | 7 npm vulns, 10 lint errors, build tolerates missing config, no py locks | **CONFIRMED** | Re-ran all four locally; numbers match to the digit — see §8 |
| AG-11 | Shutdown marks **all** running runs failed globally | **CONFIRMED** | Correct-by-topology today; breaks the instant a 2nd worker exists — precise fix in §7 |
| AG-agent (research website_url, 100/50 caps, null campaign_id, purge-before-insert, type collapse, AG-13/15/16, write-only Qdrant) | **CONFIRMED** except AG-15 **PARTIAL** | AG-15 "stranded" overstated — items 101+ are drip-fed by a 10/day top-up, not lost |

**One REFUTED claim** — my own hypothesis that the new forge provider leaks `VIDEO_FORGE_API_KEY` into logs/ledger. Adversarial recheck **upheld the refutation**: the key travels only in the `X-API-Key` header, never a URL/body; failure logs carry `str(exc)` (URL only, never headers). The forge credential path is clean.

---

## 2. Corrections — where the report is inaccurate on the mechanism

### 2.1 P0-01 is real *and I proved it* — but the report missed why it went unnoticed
Installed `langgraph` is 1.1.3. I ran a live probe: a graph compiled with `MemorySaver` that hits `interrupt()` **returns normally** with an `__interrupt__` key — no exception. So the worker's `except GraphInterrupt` handler (`worker.py:2625-2637`, the only writer of `paused_for_review`) is **dead code** — it can never fire. `grep` finds zero occurrences of `__interrupt__` or `Command(resume` anywhere in the codebase. The bug **self-masks**: `get_latest_strategy` accepts any `status='completed'` row, so the mislabeled interrupted run satisfies planning and the pipeline proceeds on a strategy **no human approved** — activation completes end-to-end, which is exactly why nobody noticed. Even if a resume were wired, `human_review` routes to `END` on both branches (`strategy/graph.py:54-56`), so the "provide feedback for revision" promise has no supporting edge. **This is a rebuild, not a patch.**

### 2.2 P0-06 is *more* broken than the report says
Beyond the tier-filter/notes-encoding mismatch: the adaptation nodes write `status='applied'`/`'rejected'`, but the DB `CHECK` constraint (`db/init.sql:343-346`) permits neither value. So even if you fixed the tier filter, tier-1 would silently swallow an `IntegrityError` per row and tier-2/3 would **crash the node**. Plus tier-1 rows are stamped `'auto_applied'` at *insert* time (before anything applies them) and `'auto_applied'` is in the pending set, so every run re-loads the entire accumulated history. The learning subsystem above tier-1 is unreachable three independent ways.

### 2.3 P0-04's regression vector is wrong
The report's example — a late `pending` callback regressing a `published` item — is **impossible**: `/publish-result` 422-rejects any status other than `published`/`failed`. The real non-monotonic hazard is a **replayed/late `failed` callback** flipping an already-`published` item back to `failed` (then a retry double-posts), or a late `published` overwriting a user-cancelled state. The underlying "no monotonic guard" claim is correct; only the vector is misidentified.

### 2.4 P0-08 SVG — upload is *not* the hole
Every direct upload endpoint (brand logo, content image, product image, vendor upload) rejects SVG **and** enforces magic-byte matching — an SVG cannot be stored via upload. The actual active-content path is the server-side **logo fetch** (`brands.py:1435,1662` explicitly allow `svg` in content-type; `_clean_logo_bytes` returns SVG untouched) → stored → served by the `/files` proxy as `image/svg+xml` with **no CSP header set anywhere**. The upload-blocks-what-fetch-allows inconsistency is itself a defect the report didn't name.

---

## 3. Priority recalibration — what is *live* vs *latent*

The report grades nearly everything P0 stop-ship. That's defensible for a multi-tenant SaaS posture, but for **this deployment today** the exploitability splits sharply, and acting on that split is the difference between a 72-hour containment and a quarter of rework:

**Latent (real code defect, but gated by current topology — not currently exploitable):**
- **P0-04 double-publish** — one container, no `--workers`, APScheduler `max_instances=1`. No *automatic* duplicate exists single-process; every duplicate path is retry-mediated. Becomes live the instant you add `--workers 2` or a replica.
- **AG-11 global shutdown-fail** — correct by deployment shape (stop-then-recreate, drain fires before exit). Breaks the moment a second worker exists (break-glass `docker compose up` during the up-to-840s drain wait is the realistic trigger).
- **P0-07 notifications** — internal-only network **and zero live producers/consumers**. Dormant.
- **P0-11 leader election** — single scheduler today; landmine only under horizontal scale.

**Live today (secrets actually leaking / internet-reachable) — several the report under-prioritized:**
- **Meta access tokens in backend logs** (NEW — §4) — leaking on every failed Graph call *right now*.
- **Legacy `social_credentials` bypass the strip layer** (NEW — §4) — `meta_access_token`/`linkedin_access_token` returned to *any* role.
- **Entra group-sync un-deactivates users** (NEW — §4) — you cannot deactivate a security-group member.
- **`/files` + `/brands/{id}/logos` fully unauthenticated** (§2.4 escalation) — anyone on the internet with a UUID.
- **By-the-book VPS deploy disables browser-worker + notifications auth** (NEW — §4) — the shipped `.env.vps.example` omits both keys and both services fail open on blank.
- **Public forge** — see §9 (deliberate, but startup validation doesn't enforce the key).

---

## 4. New findings the report missed (high-impact, code-evidenced)

| # | Severity | Finding | Evidence |
|---|---|---|---|
| N-01 | High | **Live Meta tokens written to backend stdout on every failed Graph call.** Token is in the URL query string; httpx's INFO request line + `str(HTTPStatusError)` embed the full URL. Routine trigger = an expired token 401ing. | `social.py:82-142`, `engagement_service.py:44-140`, `publish_service.py:123-138`; root logger INFO, no httpx suppression (`main.py:31-34`). Direct publishers `meta.py` avoid it correctly — defect is confined to 3 files |
| N-02 | High | **Legacy-format credentials bypass the sensitive-key strip.** `_SENSITIVE_GUIDELINE_KEYS` matches exact names (`access_token`…) but the still-supported `guidelines['social_credentials']` uses `meta_access_token`/`linkedin_access_token` — not in the set — so `GET /brands` + `GET /brands/{id}` return live tokens to **viewer/editor**. | `brands.py:44-70` vs `publish_service.py:31-50` |
| N-03 | High | **Entra group-sync silently un-deactivates users.** Every request, an admin/marketing-group member has `is_active` force-set True before the gate. Deactivation is reverted on the user's next request. | `deps.py:127-151` |
| N-04 | High | **By-the-book deploy ships browser-worker + notifications with auth OFF.** Both keys are absent from `.env.vps.example`/`.env.example`; both services allow-on-blank; no prod startup guard (unlike `N8N_WEBHOOK_SECRET`). | `browser-worker/config.py:19`, `notifications/config.py:33`, `config.py:189` |
| N-05 | High | **Browser-worker SSRF is full-read, not blind.** `/capture/extract` returns 50k chars of the target body; `/capture/screenshot` renders it to MinIO and returns the URL — cloud-metadata / internal admin pages directly exfiltrated. Reachable via authenticated user's brand/competitor URL fields. | `browser-worker/capture.py:45-129`, `main.py:188-196` (substring routing) |
| N-06 | High | **Product-intel's two most expensive nodes are DB no-ops.** `match_products_to_brands` writes results into `product["metadata"]` and `source_product_images` writes `product["image_url"]`, but `upsert_product`'s SQL touches neither column (they don't exist — images live in `primary_image_url`). Matching + image sourcing silently discarded every run. | `product_intel/nodes.py:222-257` vs `database.py:418-425`, `db/init.sql:55-85` |
| N-07 | High | **Vendor grouping reads a nonexistent key — whole catalog collapses to "Unknown".** DB rows expose `vendor_name`/`vendor_no`; code groups on `p.get("vendor")` (only the Fabric fallback ever sets it). Brand discovery/matching runs blind on the primary path. | `product_intel/nodes.py:73,192,296` vs `db/init.sql:73-74` |
| N-08 | High | **A zero-item LLM outage wipes the whole planned calendar and reports success.** `store_calendar` purges Jan-1→horizon with no minimum-item guard; `generate_calendar` swallows batch failures and returns `[]` without `status='failed'`. | `planning/nodes.py:1883-1885,1955,2273-2276,2358` |
| N-09 | High (2nd-order) | **Interrupted strategy runs poison `get_latest_strategy`** with a wrong-shaped, unapproved payload (`pillars` vs `content_pillars`), producing duplicate conflicting keys in the blob fed to the campaign LLM. | `worker.py:2234-2254` vs `strategy/nodes.py:345-356` |
| N-10 | Med | **Adaptation status values violate the DB CHECK** (`applied`/`rejected` not allowed) — see §2.2. | `db/init.sql:343-346` vs `adaptation/nodes.py:48,100-155` |
| N-11 | Med | **Forge auth misconfig silently fails over to paid cloud.** `available()` probes only the unauthenticated `/health`, so a wrong/empty `VIDEO_FORGE_API_KEY` passes, `submit` 401s, broad `except` routes to fal at ~$0.06/s. Startup validation never requires the key. | `video.py:260-271,732-735`, `config.py:204-227` |
| N-12 | Med | **Zeroed adapter strength renders at full strength.** `float(rows[0]["strength"] or 1.0)` coerces a legitimate `0.0` (schema permits it) to `1.0`. Should be `is None`-guarded. | `video/nodes.py:5065,5365,5577,5827` |
| N-13 | Med | **Traefik dashboard admin password echoed in plaintext into the CI deploy log** — violates the workflow's own "never echo secrets" rule; regeneration path can recur it. | `vps-redeploy.sh:113`, `deploy.yml:24,72-91` |
| N-14 | Med | **n8n-fallback channels re-post every scheduler tick** until the callback lands — any non-`published` 200 (e.g. n8n's async ack) leaves the item `scheduled`; up to ~288 duplicate posts/day if the callback fails. Code even records the precedent ("Teams used to re-post every 5 min"). | `publish_checker.py:263-278` |
| N-15 | Med | **Secret-config asymmetry marks live posts `failed`.** Outbound omits `X-Webhook-Secret` when unset "so dispatch keeps working," but inbound `/publish-result` 503-rejects when unset — a successful platform post is recorded `failed`, inviting a duplicate retry. | `publish_service.py:313-315` vs `webhooks.py:24-26` |
| N-16 | Med | **`alembic env.py` metadata omits `brand_model_profiles`** (no ORM model exists) — a future `--autogenerate`, which `SETUP-REMAINING.md:170` still instructs, would emit `DROP TABLE brand_model_profiles` and drop the hand-written partial indexes. | `alembic/env.py:12-29` |
| N-17 | Med | **`idx_engagement_metrics_content_fetched` exists only in `init.sql`** (added 2 days *after* the baseline) — prod can never receive it via migrations. Concrete instance of the drift the report predicted. | `init.sql:670`, git `624e936` |
| N-18 | Low | **`store_content` lacks the null-byte sanitation `store_calendar_items` has** — a `\x00` in an LLM caption aborts the content run at its final persist, after all generation cost. | `database.py:361-384` vs `437-457,616-630` |
| N-19 | Low | **`NEXTAUTH_SECRET` validated nowhere** — missing secret is completely silent at build/boot; NextAuth 500s per-request on first sign-in. Report wrongly lumped it under the Azure FATAL log. | `auth.ts:8-10,161` |
| N-20 | Low | **Deploy entry-point self-contradiction** — `deploy.yml` calls `markai-deploy` an argv-validating wrapper; `vps-redeploy.sh:6-8` calls it "a symlink to this file." If the symlink is truth, the sudoers rule forwards arbitrary root flags (`--force-wipe`). One of the two docs is wrong and the safe one is unverifiable from the repo. | `deploy.yml:4-30`, `vps-redeploy.sh:6-8` |

Also confirmed present but lower-priority: chained-lane motion gate keeps a frozen shot after one retry (report only flagged the native lane, which actually hard-falls-back); `LITELLM_MASTER_KEY` sprayed as Bearer to an endpoint that needs no auth; Teams webhook URL persisted + broadcast on failure; LinkedIn mockup hardcodes "Health & Wellness · 1,234 followers" for every brand; music-bed docs contradict the shipped tree (15 beds committed into a dir the Dockerfile says "ships empty").

---

## 5. Enhancement — the alembic story is a crash, not a shortfall

The report says fresh DBs "can't be built from migrations alone." Precise reality: `alembic upgrade head` on an **empty** DB doesn't just under-build — `0002` immediately `REFERENCES brands(id)` (absent) and `ALTER TABLE calendar_items` (absent) and **crash-loops the backend**. The split is *deliberate and self-consistent at HEAD* (init.sql declares itself the fresh-install authority; `0002` exists to converge historical hand-drift; `brand_model_profiles` is a verbatim mirror). But the discipline **already failed once within 48 hours** (N-17), and the worst-affected doc is the operational one: `VPS_DEPLOYMENT_GUIDE.md:88` still tells operators "Alembic isn't in use yet — hand-run this `ALTER TABLE`," which is precisely the drift mechanism `0002` was written to repair.

---

## 6. Enhancement — the quality gates are a *philosophy*, and it's coherent-but-unfinished

Every fail-open the report lists is real and I confirmed each with fresh line numbers. But they're not accidental `except` swallows — the pipeline's explicit contract is **"record, don't block"**: every degraded outcome (`overlay_burn`, `audio_finish`, `label_guard`, `multishot_fallback`, `branding_review`) is measured and persisted to `video_jobs.generation_ledger` / `generation_metadata`. The gap is the **last mile**: nothing downstream ever *reads* those flags to hold, escalate, or even visually mark an item — so review is "normal" in exactly the sense the report means. This reframes the fix from "add gates" (they exist as measurements) to "make review consume the flags the pipeline already writes." Cheaper than the report implies. Two the report missed: the label guard samples only **one mid-window frame per shot** (boundary lettering never checked), and detected copy-contract breaches on *ad* posts are report-only even when the critic **succeeds** and finds the breach.

On the `+1.9 dBTP` music bed: confirmed by measurement (`ffmpeg ebur128`, `bold_1.m4a` = +1.9 dBFS, 14 siblings −0.4 to −1.2). But it **cannot clip a delivered reel** — beds enter at −18/−6 dB and the final mix passes a −3 dB brick-wall limiter at 192 kHz oversampling. Provenance is "ACE-Step 1.5 (MIT)" — AI-generated, recorded only in the git commit message. Real defect = the missing in-tree manifest, not a loudness hazard.

---

## 7. Enhancement — AG-11 precise fix (the report asks for one; here it is)

**Today:** functionally correct by deployment shape, not enforcement. The global `UPDATE agent_runs SET status='failed' WHERE status='running'` (`worker.py:2850-2856`) is safe only because deploy is stop-then-recreate and the backend never inserts `running` rows. **The instant a second worker exists** it breaks concretely: worker A's drain fails worker B's live runs; B's `complete_agent_run` silently no-ops (`WHERE status='running'`) so a *successful* run is recorded failed and its output discarded; failing the row also releases the `idx_agent_runs_running` dedup lock, permitting a duplicate concurrent run — for video, a duplicate **paid GPU render**, the exact thing the drain triage exists to prevent.

- **Minimal fix (no migration):** the worker already has each run's ID (`create_agent_run` returns it). Record it into the in-flight registry entry, then scope the drain release to `WHERE id = ANY(:ids) AND status='running'`.
- **Durable fix (migration):** add `claimed_by TEXT` (+ `heartbeat_at`), stamp a per-process `WORKER_ID`, drain `WHERE status='running' AND claimed_by=:worker_id`, and convert the age-only `stale_run_reaper` to heartbeat expiry — which also closes the report's **BE-34**.

Related new items: brand-deactivate frees the dedup lock while the un-killed workflow still runs → reactivate → two concurrent runs (reachable from the UI); the audit-log wipe (`DELETE` with no `WHERE`) is itself **unaudited** (no `record_audit` call) so the destruction leaves no trace of who or when.

---

## 8. Enhancement — I re-ran the report's "executed checks" table; it holds to the digit

| Check | Report | My local run (2026-08-21) |
|---|---|---|
| `npm audit --omit=dev` | 2 critical, 4 high, 1 moderate (7) | **Exact match.** 6 of 7 fix via non-breaking `npm audit fix`; only `@auth/core` needs `--force` |
| `npm run lint` | 10 errors, 71 warnings | **Exact match** (81 problems). `WorkflowStatus` has **two** set-state errors (48, 58), not one; the other 3 errors are `no-explicit-any` in `BrandOnboarding:67` and `no-empty-object-type` in `input.tsx`/`textarea.tsx` |
| `npm run build`, config unset | Builds despite FATAL | **Confirmed by execution** — printed the Azure FATAL, generated all 21 pages, exited 0. `NEXTAUTH_SECRET` gets *no* diagnostic at all (N-19) |
| Backend ruff | 5 issues | **Exact match** |
| Agent ruff | 41 issues | **Exact match** |
| Python lockfiles | none | **Confirmed** — 4 PEP-621 `pyproject.toml`, floor-only pins, `uvicorn[standard]` fully unconstrained; only the JS side is locked. (Note: services are `browser-worker/` + `notifications/` at repo root, not under `services/`) |

---

## 9. The one recommendation to reject: INF-01 / P0-07 "Remove public Forge routing"

This conflicts with an explicit product requirement (the forge is deliberately published so any MarkAI deployment can reach the local GPU via URL + key). My verification **confirms the report's exposure facts** and adds two the report didn't have: the `forge-proxy` sits on the **shared external `n8n_default` network** (other tenants' containers reach `markai-forge-proxy:9100` directly, bypassing the Traefik rate limit), and the relay is **path-blind** (every tunnel endpoint is published), so the *entire* security boundary is the forge-side key. Therefore the correct action is **hardening, not removal**:

1. **Enforce `VIDEO_FORGE_API_KEY` at forge startup** (today production validation checks only Postgres/MinIO/LiteLLM — a blank key silently disables the boundary and fails MarkAI over to paid cloud, N-11).
2. Move `forge-proxy` off the shared external network or bind the relay to a dedicated internal network + IP-allowlist the tunnel origin.
3. Consider mTLS or a Tailscale ACL on the tunnel (already a pending user action) so `/health` isn't the only thing an unauthenticated scanner can touch.

Runtime logs already show external scanners hitting the endpoint, so this is not theoretical — but the answer is to make the key mandatory and the network private, not to unpublish a deliberately-published service.

---

## 10. Bottom line

The report is trustworthy — endorse its P0 register. My enhancements: **fix its four mechanism errors** (§2), **sequence the work by the live/latent split** (§3) so containment targets the secrets leaking *today* (N-01/02/03/04 + unauth `/files`) ahead of the multi-tenant-scale landmines, **fold in the ~30 new findings** (§4, several higher-impact than items it flagged), and **treat the public forge as accepted-risk-with-hardening** (§9) rather than removing a required capability. The single highest-value *new* action not in the report: stop the Meta-token log leak and the legacy-cred strip bypass — those are live credential exposures the report's own P0-03 narrowly missed.
