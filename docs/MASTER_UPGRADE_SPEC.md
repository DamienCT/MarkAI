# MarkAI — Master Upgrade & Video Factory Specification

> **Version:** 1.0 — 2026-08-18
> **Mission:** Evolve MarkAI into the most competent and complete autonomous digital-marketing agency:
> state-of-the-art platform-native content (posts **and short-form video**), provider-agnostic AI inference
> including a **local RTX 4090 video server**, latest-generation models everywhere, and a hardened, self-healing
> factory that takes a brand from onboarding to published, measured content with minimal human touch.
> **First proof:** onboard **Naturespan.mu** and fill a 2-week Instagram/Facebook/YouTube pipeline
> (countdown to the Sept 1 store openings), including product-promo videos.

This document is the standing reference for the whole program. It was produced from an 11-subsystem code
audit and a 9-topic live-web research sweep (reports in the session scratchpad under `audit/` and `research/`).

---

## 1. Where we start (audit digest)

**What already works well:** a real autonomous pipeline exists — brand activation chains research → strategy
→ planning (52-week calendar) → 13-node content generation (hook/caption/hashtags, gpt-image scene, Gemini
real-product swap, vision-planned branding overlays, per-channel adaptation, mockups) → approval →
scheduled publish (IG/FB images, LinkedIn text) → engagement pull. Multi-brand, BC/Fabric product sync,
model registry with admin UI, Entra ID SSO, 16-service Docker stack behind Traefik.

**Video is pre-wired but inert:** `content.video_url` + `media_assets` columns, `item_type='reel'` accepted
end-to-end, a dormant `video` model category in `_categorize_model`, sora entries in LiteLLM config, dispatch
falls back to `video_url`, `engagement_metrics.video_views` exists. Missing: everything that writes them.

### Critical defects (fix before/while building — P0)

| # | Defect | Where |
|---|--------|-------|
| D1 | `get_product_by_bc_item_no` has **no brand_id filter**; second BC company steals/ping-pongs product rows every sync. **Blocks Naturespan onboarding.** | `backend/app/services/product_service.py:40-44` |
| D2 | Redeploy backup runs pg_dump against a stopped DB → **always writes an empty gzip**, prints "Backup complete"; `--force-wipe` trusts it | `scripts/vps-redeploy.sh` L66-94 |
| D3 | `trending_topics`, `channel_model_fallbacks` have **no DDL anywhere**; `calendar_items` CHECK lacks `'planned'` — fresh install breaks; prod schema is hand-drifted. No Alembic migrations at all | `db/init.sql`, `backend/alembic/` |
| D4 | Per-platform adaptations are publish-dead: pipeline writes `generation_metadata.platform_adaptations`, publish reads `content.platform_metadata` (never written) | `publish_service.py:183-185` |
| D5 | n8n publish workflow has **no error branch** — failures resolve only via >1-day stale sweep; LinkedIn post ID always "unknown" (URN is in `x-restli-id` header) breaking LinkedIn analytics; Teams re-posts every 5 min | `docs/n8n-workflows/markai-publish.json` |
| D6 | Daily evaluation trigger published without `brand_id` → evaluation **never runs**; strategy human-review interrupt broken (MemorySaver, no resume); `paused_for_review` violates the status CHECK | `morning_jobs.py:76-82`, `strategy/nodes.py:292-322` |
| D7 | Hardcoded `openai/` LiteLLM prefix blocks every non-OpenAI model through the registry; image gen bypasses LiteLLM (direct api.openai.com); `gemini-2.5-flash-image` hardcoded ×3 | `agents/shared/llm.py:135,490-541` |
| D8 | Public unauthenticated file proxy, no video MIME, whole-object RAM buffering, no Range requests | `backend/app/api/v1/files.py` |
| D9 | Plaintext social tokens in `brand_guidelines` JSONB, unmasked to manager+, in n8n logs | `brands.py`, `publish_service.py` |
| D10 | Single serial agents consumer (~3-5 min/post blocks everything); stale `running` agent_runs deadlock brands; no DLQ; NATS stream config changes silently swallowed | `agents/worker.py`, `nats_service.py:44-53` |
| D11 | Token/cost accounting dead (`accumulate_tokens` 0 callers); Qdrant write-only (embeddings never searched) | `agents/shared/llm.py`, `vector.py` |
| D12 | agents browser client calls endpoints that don't exist on browser-worker (`/screenshot` vs `/capture/*`) and omits `X-API-Key` — silently degrades to plain fetch | `agents/shared/tools/browser.py` |
| D13 | Frontend: approvals page never shows the image; Kanban DnD is dead code; 9 polling loops, no push; stale hand-written types | `approvals/page.tsx:174`, `KanbanBoardInner.tsx` |
| D14 | Retired/dying model IDs: config pins gpt-5.4-era models, sora-2 (API dead Sept 24 2026), gemini-2.5-flash-image (superseded), dall-e still selectable | `litellm/config.yaml`, registry seeds |

---

## 2. Locked technical decisions (from research, verified Aug 18 2026)

### 2.1 Local video engine — **LTX-2.5** on the RTX 4090
- Checkpoint: `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (21.5 GB; int8 **not** NVFP4 —
  NVFP4 is Blackwell-only, 4090 is Ada). Full pack ~50 GB, 6 files, HF repo `Lightricks/LTX-2.5` (gated —
  **user must accept license + provide HF read token**).
- Verified VRAM budget: transformer 20.03 + video VAE 1.37 + audio VAE 0.34 + spatial upscaler 0.93 =
  **22.67 GiB / 24** — works IF the Gemma-4-12B text encoder is freed before sampling (VRAM-cleanup node,
  no `--highvram`). System RAM: 192 GB (3× the requirement). ~1.5–4 min per 5s clip w/ synchronized audio.
- Native image-to-video (product keyframe conditioning), native audio, multishot; ≤121 frames (~5s @ 24fps)
  per pass; 9:16 at 704×1280 (preset) — longer clips via multishot/FLF2V chaining (R&D) or cloud.
- License: LTX-2.x Community — free commercial < $10M revenue, outputs owned by us.
- Fallback local engine (phase 2): **Wan 2.2** (Apache 2.0) + per-brand product LoRA for consistency.
- Runner-up rejected: HunyuanVideo (Tencent license, EU exclusion), diffusers path (unreleased main only).

### 2.2 Serving & connectivity
- **Headless ComfyUI** v0.32+ bound to `127.0.0.1:8188` (never exposed — exposed ComfyUIs = RCE/botnet)
  behind a **thin FastAPI job gateway** on `:9100`: `X-API-Key` auth, SQLite job store, `POST /v1/jobs` → 202
  `{job_id}`, `GET /v1/jobs/{id}` (status/progress via ComfyUI WS), webhook to VPS on completion, MP4 uploaded
  to VPS MinIO (never streamed through the tunnel inline). Queue depth 1, 30-min hard timeout → `/interrupt`.
- **Tunnel:** start with **reverse SSH** (`ssh -R 9100:127.0.0.1:9100` to the VPS, loopback-bound both ends —
  zero new auth, works today); upgrade to **Tailscale tailnet** (already installed+logged-in on the PC; VPS
  join needs one user-approved auth). Cloudflare Tunnel = documented fallback (100 MB body cap).
- Auto-start: Windows services via WinSW/NSSM + Task Scheduler; verify cold-reboot unattended.
- The same gateway later serves image models (Flux-schnell/SDXL, Apache-safe only) from the same ComfyUI
  instance — `POST /free` between model-family switches; **never** two ComfyUI processes on one 4090.

### 2.3 Cloud video fallbacks (provider-agnostic layer)
- **Adapters wave 1:** local gateway + **fal.ai** (queue API + ED25519-signed webhooks; `fal-ai/ltx-2.3/image-to-video`
  $0.06/s as cloud twin; `kling-video/v3` as quality step-up) + **Veo 3.1** via Gemini API
  (`veo-3.1-fast-generate-preview` $0.10-0.12/s; polling only; outputs deleted after 2 days → download immediately).
- **Never Sora** (API shuts down 2026-09-24). Optional premium later: Seedance 2.5 via fal.
- Canonical contract: `{mode: i2v|t2v, prompt, image_url, last_frame_url?, duration_s, aspect, resolution,
  audio, seed?, quality_tier, budget_usd_max, idempotency_key}`; adapters implement
  `capabilities/estimate_cost/submit/poll/handle_webhook/cancel`; statuses normalized to
  `queued|running|succeeded|failed|canceled`; **always re-host outputs to MinIO before acking**.
- Routing: draft→local→fal-LTX; standard→local→fal-LTX→fal-Kling; hero→Veo Fast/Standard→Kling Pro.
  Health-check local tunnel (5s) and spill to cloud on failure/deep queue.

### 2.4 Creative process — port the open-sourced Higgsfield pipeline ("The Cully Hill Boys")
- **Assets first:** brand asset lock during onboarding — multi-angle product sheets on neutral grey, logo
  variants, palette, location/set sheets. Our existing branded-keyframe generator (gpt-image scene + Gemini
  product swap) is the keyframe factory for I2V.
- **Structured prompts:** CINEDANCE/MCSLA schema per shot — SCENE CONTEXT / ACTIVE @refs / FIRST FRAME /
  explicit CUTs / OPTICS (degrees) / LIGHTING (Kelvin) / diegetic AUDIO / STYLE / LOCKS. MIT reference:
  `OSideMedia/higgsfield-ai-prompt-skill` (incl. product-ad/product-UGC templates).
- **Iteration rules:** change one thing at a time; re-describe everything every take; log every generation
  (prompt hash, seed, changed element, verdict) in a **generation ledger** driving auto-retry + takes-per-keep analytics.
- Video subgraph skeleton per HKUDS/ViMax (MIT): brief → script → shot-list JSON → per-shot gen with product
  reference + first-frame conditioning → assembly; VLM monitoring throughout.

### 2.5 Master render & platform specs (verified against official docs)
- **One master render serves all platforms:** 1080×1920 (9:16), H.264 High + AAC 128k/48kHz, 30fps CFR,
  closed GOP 2s, moov-atom-first, ≤300 MB, target 20–35s (hard max 90s = FB Reels API limit).
- **Safe zones** (Meta unified, superset of IG/YT): top 270px, bottom 670px, sides 65px on 1080×1920 —
  text/logo/CTA inside centered ~950×980 rectangle; ship a QA debug-grid export.
- **Publish flows:** IG Reels container (`media_type=REELS`, resumable upload, poll `status_code` FINISHED,
  then `media_publish`; 100/24h — verify via `content_publishing_limit`); FB `video_reels` 3-phase (30/Page/24h);
  YouTube `videos.insert` (Shorts auto-classified ≤3min vertical; `containsSyntheticMedia=true`; quota 100/day;
  **unaudited API projects force uploads private** — start compliance audit); LinkedIn Videos API
  (initializeUpload → 4,194,304-byte chunks → finalize → poll AVAILABLE → posts; needs Community Mgmt partner access).
- **2026 norms baked into generators:** IG ≤5 hashtags (penalty above), hook in first 125 chars; hook visual
  in seconds 0–2, scene change every 1.5–2s, burned-in captions, CTA last 3s, loopable end; LinkedIn 3–5
  hashtags, ~140-char visible hook; YT keyword-first titles.

### 2.6 Model assignments (all via LiteLLM; IDs verified live)
| Task | Primary | Notes / fallback |
|------|---------|------------------|
| Strategy, planning, video direction | `claude-opus-5` ($5/$25) | `gpt-5.6-sol` |
| Captions, hooks, briefs | `claude-sonnet-5` ($2/$10, permanent) | `gemini-3.7-flash` |
| High-volume adaptations, scoring | `gemini-3.7-flash` ($0.75/$3.75 intro) | `gpt-5.6-luna` |
| Branded product images | `gemini-3.1-flash-image` (Nano Banana 2) | hero: `gemini-3-pro-image`; alt `gpt-image-2` |
| Image edit / product swap | `gemini-3.1-flash-image` (new `image-edit` category) | replaces hardcoded 2.5 |
| Vision critic / QA | `claude-sonnet-5` (cross-vendor vs generator) | volume: `gemini-3.7-flash` |
| Video (cloud) | `veo-3.1-fast-generate-preview` | `fal ltx-2.3`, `kling v3` |
| Video (local) | LTX-2.5 int8 via Video Forge | Wan 2.2 later |
| TTS | ElevenLabs `eleven_v3` (hero) / Kokoro-82M CPU (bulk, EN+FR) | Qwen3-TTS clone tier |
| STT / subtitles | local `faster-whisper large-v3` (CPU ok) | `gpt-transcribe` |
| Embeddings | `text-embedding-3-small` (keep 1536-dim) | voyage-4 later |
- **Dead/dying:** Imagen 4 (shut down Aug 17), Sora API (Sept 24), dall-e-2/3, gemini-2.5-era image models.
- Structured outputs: migrate all `json_object`+regex parsing to strict `json_schema`.

### 2.7 Architecture patterns to adopt
- LangGraph 1.2.x + **Postgres checkpointer** (durable execution, `interrupt()`/`Command(resume)` HITL —
  fixes the broken approval interrupts; Agent-Inbox typed schema for the approval UI).
- Two-stage QA gate on every asset: cheap VQAScore-style alignment filter over N candidates → rubric VLM
  judge (logo presence/placement, palette, claim accuracy, safe margins, legibility) → ≤2 refine retries →
  human card. Deterministic checks (OCR, logo pixel-position, safe-zone) alongside — VLM judges miss fine text.
- Brand memory: semantic (facts, palette, **banned claims**), episodic (posts + outcomes), procedural
  (voice rules refined from human edits) — LangGraph Store; retrieval into prompts at generation time
  (activates the write-only Qdrant).
- Publishing as resumable per-platform state machines (create→upload→poll→publish→verify) with persisted
  container IDs/URNs — replaces the n8n hop for video; n8n stays as image-path fallback until parity.
- OSS to integrate (license-clean): MoneyPrinterTurbo patterns (MIT, provider abstractions, dual subtitles),
  Remotion captions **only if team ≤3 people** else ffmpeg/ASS (decide once), marketing-skills repos (MIT)
  as vendored `skills/`, changedetection.io + trendFinder patterns for intelligence (phase 3), Postiz only
  ever via HTTP sidecar (AGPL). n8n must never be embedded (fair-code).

---

## 3. Program plan

### Phase 0 — Foundation & safety net *(repo: MarkAI)*
1. Alembic baseline from live prod schema; add missing DDL (`trending_topics`, `channel_model_fallbacks`,
   `events`), status CHECK fixes (`planned`, `rendering`, `paused_for_review`); CI schema gate; delete lifespan DDL.
2. Fix D1 (brand-scoped product upsert `ON CONFLICT (brand_id, bc_item_no)`), D2 (pg_dump before `down`,
   `gzip -t` verify, + nightly backups incl. MinIO mirror), D5 (n8n error branch + LinkedIn URN header — or
   leapfrog straight to in-backend publishers), D6 (evaluation brand_id fan-out; checkpointer groundwork), D12.
3. Model plumbing: kill `openai/` hardcoding (registry returns provider+model), seed `video`/`image-edit`/
   `tts`/`stt` categories, LiteLLM upgrade + new model IDs, route image gen through the registry cascade,
   wire `accumulate_tokens` + model provenance.
4. Media serving: mp4/webm MIME + Range streaming (or presigned redirects) in files.py; `videos` bucket.
5. NATS: new `VIDEO` stream (WorkQueue retention, own ack_wait, DLQ) — new stream because config changes to
   the existing one are silently swallowed; stale-run reaper.

### Phase 1 — Video Forge *(new repo: `D:\markai-video-forge`)*
- ComfyUI headless install + LTX-2.5 int8 pack (blocked on user's HF token) + exported API-format workflow
  JSONs (`i2v_9x16_5s` first; upscale-to-1080p second; multishot chaining R&D third).
- FastAPI gateway (auth, jobs, progress, webhook, MinIO upload, generation ledger) + presets + Windows
  services + reverse-SSH tunnel unit + healthcheck endpoint the VPS can probe.
- Bench on this box: `--highvram` on/off A/B, real wall-times, WDDM behavior. Wire local model as a provider
  row reachable from the VPS.

### Phase 2 — Video pipeline in MarkAI
- `video_jobs` table + `media_assets` table; VideoProvider abstraction (local/fal/veo) with the §2.3 contract.
- `video` LangGraph workflow: reuse content nodes 1–5 → shot-list (CINEDANCE schema) → branded keyframe(s)
  via existing image pipeline → I2V per shot → assembly (ffmpeg: master spec §2.5, music bed, ducking,
  burned-in word captions via faster-whisper timestamps) → VLM QA gate → store → approval.
- Flip planner `content_format` default to mixed (`reel` items flow); parallel-safe worker scaling
  (queue-group consumers) so video renders don't block posts.
- Frontend: content-type selector, video player in previews/approvals/lightbox, video pipeline tracker
  steps (server-driven), providers page video category; SSE push channel replacing the 9 polling loops.
- Publishing: in-backend ChannelPublisher state machines for IG Reels / FB Reels / YouTube / LinkedIn video
  + per-platform validators + quota guards; encrypted `brand_credentials` table.

### Phase 3 — Content quality SOTA (posts + video)
- Channel-profiles table = single source of truth (caps, hashtag rules, safe zones, hook rules) consumed by
  generators AND validators; platform adaptations actually used at publish (D4).
- Multi-candidate generation + judge for hooks/captions/images; extend vision critic to ad format; critic
  loop with convergence cap; base-image re-roll.
- Learning loop: embed published content + engagement into Qdrant `content_memory`; retrieve top performers
  per channel/pillar at prompt time; evaluation workflow actually running (D6) feeding adaptation tier-1
  mutations (post times, hashtag policy, cadence).
- Brand guardrails: per-brand banned-claims list enforced by a deterministic + LLM claim-checker QA node
  (Naturespan's 12 guardrails are the first dataset).

### Phase 4 — Naturespan onboarding + 2-week pipeline
- Verify Naturespan BC company in Fabric `lh_bronze`; onboard brand (logo from `naturespan.mu/logo.png` +
  Downloads assets; brand bible from site + shop + business plan + audit docx; guardrails §above; FR/EN voice);
  BC sync with vendor/category filters; vendor logo pass.
- Activate content factory: research → strategy → planning scoped to Aug 18 – Sep 1 **store-opening countdown**
  (Grand Baie + Tamarin, Sept 1) + evergreen certification-trust pillars; generate ~2 weeks of IG/FB/YouTube
  content incl. product-promo videos; everything lands in **in_review** (nothing auto-publishes).
- QA pass over every generated asset (guardrail compliance, visual QA, platform validators) before handing
  to the user for review.

### Phase 5 — The upgrade-audit loop (×5, up to ×15)
Each cycle: (1) run the full QA battery — tests, generation samples, visual/claims QA, pipeline health on
VPS; (2) triage findings; (3) upgrade code/features/prompts/models/efficiency; (4) re-verify; (5) record in
`docs/UPGRADE_LOG.md`. Stop when a cycle yields no material findings (≥5 cycles, ≤15).

---

## 4. Deployment & environments
- Local dev mirrors VPS (same compose); Video Forge runs on Windows host, reachable from VPS through the
  tunnel; local testing uses the same gateway URL pattern (`VIDEO_FORGE_URL`).
- VPS deploys stay `ado`-driven via fixed `vps-redeploy.sh`; dual-push GitHub + ADO on every commit batch.
- Observability profile enabled in prod + alerts on NATS lag / agent_runs failures / video job failures.

## 5. Actions only the user can do
1. **HuggingFace:** accept the `Lightricks/LTX-2.5` license and provide a read token (`HF_TOKEN` in
   `markai-video-forge/.env`) — blocks the ~50 GB model download.
2. **Tailscale (optional upgrade over reverse SSH):** approve the VPS join (one auth URL).
3. **YouTube:** start the API compliance audit (unaudited projects = uploads forced private) — content can
   still be generated/reviewed meanwhile.
4. **LinkedIn:** apply for Community Management API partner access (video posting) — text posts work today.
5. **Remotion licensing question:** is the team ≤3 people? (Free tier) — otherwise we standardize on
   ffmpeg/ASS captions (default assumption until answered).
6. ElevenLabs API key if hero-tier TTS voiceovers are wanted (Kokoro local covers bulk for free).

## 6. Success criteria
- A brand can be onboarded and produce platform-perfect posts **and** 5–30s product-promo videos with
  ≤1 human touch (approval), across IG/FB/LinkedIn/YouTube.
- Video renders locally on the 4090 (cost ≈ $0) with automatic cloud spill; any provider swappable by config.
- Every asset passes deterministic + VLM QA incl. brand guardrails before a human sees it.
- Naturespan: 2 weeks of countdown + evergreen content in review, incl. videos, zero guardrail violations.
- The system measurably improves itself: engagement → memory → next-cycle prompts; cost per asset tracked.
