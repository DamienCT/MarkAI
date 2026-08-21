# AI Server Program — local GPU forge as a first-class, portable service

Directive (2026-08-21): MarkAI must run on both local models and API models
(gpt-image-2 / Sora), offer per-brand fine-tuned models for image AND video,
keep the local AI server alive whenever the operator is signed in, publish it
on the open internet behind an API key + URL so ANY MarkAI deployment can use
it, and drive local video quality to meet or beat a Sora A/B on the same
script — with a standing research loop until that bar is met.

This document is the architecture + status ledger for that program.

---

## 1. Provider matrix (dual local/API, both media types)

| Media | Local (4090 forge) | API |
|---|---|---|
| Image | Z-Image / Qwen-2512 / FLUX.2-klein-4B / Chroma presets via ComfyUI | OpenAI gpt-image-2 (live today: keyframes, content images) |
| Video | LTX-2.5 int8 22B distilled, native multishot joint-AV | fal.ai LTX (fallback, live), Veo 3.1 (hero tier, live), Sora 2 Pro (benchmark-only — see §5) |

**Sora reality check (verified 2026-08-21 against OpenAI's own docs):** the
entire Sora line is discontinued. The app died 2026-04-26; the API and all
sora-2* models shut down **2026-09-24**, no successor announced. The API works
until then: sora-2-pro renders native 9:16 1080x1920, 4–20s per generation
(extensions to 120s), synchronized audio, ~$0.70/s standard. Hard constraints:
input reference images may not contain human faces, no real-person likeness,
under-18-suitable content only. Consequence: **Sora is a benchmark, not a
dependency** — we buy reference clips now (§5) and never build product flow on
it.

## 2. Per-brand fine-tuned models (image + video)

Verified research (see the license/tooling citations in the 2026-08-21
research pass) settled the lanes:

**Image lane — per-brand LoRA on Qwen-Image-2512 (Apache-2.0).**
musubi-tuner has an officially documented 24GB recipe (fp8 + block-swap;
needs ~64GB system RAM — this box has 192GB). ~4–6h overnight per brand,
20–40 product/brand photos with a per-brand trigger token. Runner-up:
FLUX.2-klein-4B via ai-toolkit (~1h per brand, BFL-documented) — also the
zero-training packshot path via klein's multi-reference conditioning.
Inference: the forge injects the brand's LoRA filename into the workflow
(`LoraLoaderModelOnly`); brand switching is a seconds-scale weight patch.
Trap on record: Z-Image-Turbo is officially NOT finetunable (train Z-Image
base + DistillPatch if ever needed); FLUX.2-klein-9B is non-commercial.

**Video lane — two phases.**
- *Phase 1 (zero training, available now):* per-brand reference-sheet
  conditioning with the official Ingredients IC-LoRA (one composite image:
  product, presenter, setting), ID-LoRA zero-shot presenter identity (face
  image + ~5s voice), and the I2V keyframe anchoring the pipeline already
  does. Brand identity without owning a training run.
- *Phase 2 (true adapters):* LTX LoRA via ComfyUI-LTX2-TRAINER (official
  trainer adapted; 24GB-workable, ~96GB RAM — we have 192GB), stacked with
  the distilled LoRA on the int8 pipeline exactly the way the distilled LoRA
  itself already loads. Fallback if the LTX chain fails its smoke test:
  Wan 2.2 LoRA via musubi-tuner (Apache-2.0, best-documented 24GB path) at
  the cost of joint audio + multishot.

**License obligations (LTX Community License, verified from LICENSE.md):**
fine-tunes are non-transferable Derivatives — serving adapters from OUR
hardware is fine (SaaS expressly permitted), handing adapter FILES to a
client is not; the whole stack needs a paid Lightricks agreement if MarkAI
crosses $10M revenue. Flag for counsel: whose revenue counts when reels are
made for client brands.

**Deciding smoke tests (one GPU-day each):**
- Image: train one Qwen-2512 LoRA overnight for one brand → 6-packshot grid
  with legible, geometrically-correct labels vs ground truth.
- Video: train one rank-16 LTX LoRA (~3–5h) → render the benchmark reel
  with/without adapter → score identity, AV sync, multishot continuity,
  VRAM headroom, swap latency.

**MarkAI-side schema (to implement):** `brand_model_profiles` table —
brand_id, kind (image|video), base_model, adapter_name (forge-local
filename), trigger_token, strength, status (training|ready|disabled),
trained_at. The forge JobRequest gains optional `lora_name`/`lora_strength`;
the render nodes look up the brand's ready profile and pass it through.

## 3. Local AI server: always-on + published

**Supervision (live since 2026-08-21):** four Windows Scheduled Tasks —
MarkAIForge-{ComfyUI,Gateway,Tunnel} start hidden at logon of the operator's
user; MarkAIForge-**Watchdog** runs at logon + every 5 minutes,
health-checks 8188 / 9100 / the tunnel's ssh child and restarts whatever is
down. The watchdog exists because the component tasks give up after 3
restarts and the processes have twice vanished silently hours after a
successful render. Registration: `scripts\install_services.ps1` in the forge
repo (idempotent).

**Publication (live since 2026-08-21):** the forge is reachable from the
open internet as

    https://forge.markai.srv1191974.hstgr.cloud      + X-API-Key

Path: internet → shared VPS Traefik (TLS via Let's Encrypt, rate-limited) →
`markai-forge-proxy` (a one-process socat relay container, the only way to
give a host port a docker-label route) → reverse SSH tunnel bound to the
docker bridge → the 4090's gateway. Auth lives in the forge itself: /v1/*
rejects missing (401) and wrong (403) keys; /health is deliberately open for
monitors. The tunnel + proxy hop adds nothing meaningful against multi-minute
renders.

## 4. Portable credentials

MarkAI reaches the forge exclusively through two settings (agents
`shared/config.py`, VPS `.env`):

    VIDEO_FORGE_URL=https://forge.markai.srv1191974.hstgr.cloud
    VIDEO_FORGE_API_KEY=<key>

Any future MarkAI deployment — new VPS, cloud, laptop — needs only those two
values; nothing else in the stack knows where the GPU lives. (On this VPS
the URL points at the public route rather than the tunnel-internal address
precisely so the portability claim stays continuously proven.)

## 5. Quality bar: the Sora benchmark + research loop

Because Sora dies 2026-09-24, the bar is a **frozen reference set** bought
while the API lives:

1. Render the current benchmark script (the v10 Naturespan reel's exact
   segment prose) through sora-2-pro at 1080x1920 → store under `samples/`
   and in MinIO as the reference.
2. Every planner/pipeline change that claims quality gains re-renders the
   same script locally and is compared frame-by-frame against both v10 and
   the Sora reference (composition, light coherence, human warmth, artifact
   count, label cleanliness).
3. Standing research loop (each upgrade cycle): sweep new open-source video
   models/workflows against the reference — current watchlist:
   daVinci-MagiHuman (re-evaluate ~Nov 2026), LTX point releases, Wan
   releases (only from the Wan-Video org — SEO "open Wan 2.7" claims are
   false), LTX Retake + avatar lanes (docs/VIDEO_LANES_RESEARCH.md).

Status ledger:
- [x] Supervision + watchdog live (forge repo a3205af)
- [x] Public route + credentials (this repo: forge-proxy overlay)
- [x] Sora research verified; benchmark plan set
- [ ] Sora reference clips rendered (before 2026-09-24)
- [ ] brand_model_profiles schema + forge lora passthrough
- [ ] Image fine-tune smoke test (one brand, overnight)
- [ ] Video adapter smoke test (one brand, one GPU-day)
