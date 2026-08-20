# Video Lanes Research — Retake & Avatars (2026-08-20)

Adversarially-sourced research for the two next video-factory lanes. Produced by
the cycle-13 research pass; licenses verified against the GitHub license API or
the model card itself, not third-party roundups. Wall-clock figures are
extrapolations from the ONE measured datapoint (3s/73-frame reel E2E = 24s on
the 4090) unless stated — re-measure in the smoke tests.

---

## Lane A — Retake: re-render a flagged window, keep the rest of the reel

**Verdict: buildable on the existing forge** — one new workflow JSON, one new
engine path, zero new model stacks.

### Why it works

- `LTXVAddGuideAdvanced` (already used by `multishot.py insert_guide_chain`)
  accepts arbitrary `frame_idx` conditioning — end-of-window anchoring is the
  same mechanism as the official LTX-2.5 First-Last-Frame template.
- Lightricks ships an official in/outpainting workflow: `LTXVInpaintPreprocess`
  (white=inpaint/black=keep masks) → IC-LoRA guide → 8-step distilled
  generation → `LTXVLaplacianPyramidBlend` (dilation is the key seam-quality
  setting). LTX-2.3 IC-LoRA checkpoints run on the 2.5 distilled transformer.
- Audio can be **frozen, not regenerated**: `VAEEncodeAudio` →
  `LTXVSetAudioRefTokens` passes the source audio through sampling unchanged
  (noise_mask=0) — the native answer to the joint-AV problem.

### Recommended recipe (mode=`retake`)

Extract window±1.5–2s pads from the **24fps pre-master mezzanine** (never the
delivered 30fps master), total frames ≡ 1 mod 8. VAE-encode, freeze the pads,
re-denoise ONLY the window with corrected prose (seed = original + retake
counter). Optionally Laplacian-blend over the pads to kill VAE color shift.
Splice video-only at 24fps, mux the ORIGINAL audio track untouched, re-run
master_encode. **~2–4 min per retake** vs ~6–15 min full re-render.

Fallback variant if inpaint masking misbehaves on the int8 distilled AV graph:
FLF2V-style pass over just the window (frame 0 = last good frame via
`LTXVImgToVideoInplace` ~0.9, end anchor via `LTXVAddGuideAdvanced` 0.8–0.9),
1-frame head/tail trim like `seam_join_cmd` — zero new node types, weaker
motion continuity.

### Riskiest assumption (smoke test FIRST)

Mid-video windowed resample at 8 distilled steps landing motion- and
exposure-continuous at BOTH seams — the Kijai "Extend Any Video" discussion
explicitly reports mid-video retakes are weaker than end-extension. Test: retake
seconds 18–21 of an existing reel with the SAME prompt, scrub both seams
frame-by-frame + vectorscope the window. If seams pop at 1.5s pads, escalate
toward the community's 73-frame (3s) overlap recommendation.

### Hard dependencies

- **Retention**: retakes need the 24fps mezzanine; forge `RETENTION_HOURS=48`
  deletes it. Persist mezzanines longer for QC-flagged reels.
- **Byte-identical honesty**: the v1 full re-master (x264 re-encode) makes
  "rest of reel byte-identical" impossible — v1 is visually-identical. A v2
  GOP-aligned smart-copy (master already has closed 2s GOPs) can achieve
  byte-identical video outside a ±2s-quantized window.

---

## Lane B — Avatars: talking presenters, consistent across a reel

**Verdict: do NOT bolt on a second heavyweight avatar stack first.** LTX-2.x
has native audio-conditioned talking-character generation (reference image +
audio + prompt, no adapters), plus an official LipDub IC-LoRA.

### Top pick: LTX-native avatar mode

**Chatterbox TTS (MIT) → frozen-audio LTX-2.5/2.3 a2v from a per-brand
presenter image.** One engine, one VRAM budget, one already-accepted license.

- Workflow = `ltx25_i2v.json` + `LoadAudio` → `LTXVAudioVAEEncode` → frozen
  audio latent into `LTXVConcatAVLatent`, + `LTXVSetAudioRefTokens` on the
  conditioning; presenter image via the existing `LTXVImgToVideoInplace` node.
  frames = ceil(audio_s×24) snapped to 1 mod 8.
- **Identity consistency**: ONE approved photoreal portrait per brand (from the
  existing image forge) reused as the i2v anchor for every avatar shot; one
  stored Chatterbox voice-reference clip per brand (zero-shot cloning).
  Optional hardening: official LTX ID-LoRA per presenter (non-transferable
  Derivative under the Community License).
- **Quality honesty**: waist-up presenters at 704x1280→1080x1920 read as a
  solid HeyGen-adjacent spokesperson; hands and extreme close-ups can betray AI
  texture. Design reels 30–40% presenter / 60–70% product b-roll. A continuous
  30s talking close-up is NOT yet safe.
- 5s avatar shot ≈ 40–60s render; TTS is seconds. Fits the multishot budget.

### Runner-up / corrective: LatentSync 1.6 (ByteDance, Apache-2.0 verified)

Post-hoc lip re-sync on the final 1080x1920 clip. 18GB inference VRAM — does
NOT co-reside with the loaded int8 22B LTX stack (~4.8GB headroom): serialize
with model unload or run as a separate queued forge step. Mouth-region softness
vs surrounding detail is the visible failure mode.

### Quality-ceiling fallback: InfiniteTalk (MeiGen-AI, Apache-2.0 verified)

Best open audio-driven full-presenter motion, unlimited length — but a separate
Wan2.1-14B stack, 25fps (needs resample), and ~10–20 min per 5–10s clip on the
4090. Only if LTX-native + LatentSync both miss the bar.

### TTS

| Model | License | Note |
|---|---|---|
| **Chatterbox / -Turbo** | MIT (verified) | zero-shot cloning, emotion control, seconds on 4090; embeds Resemble PerTh audio watermark (fine for ads, know it exists) |
| Kokoro-82M | Apache-2.0 | near-instant utility voice, no cloning |
| F5-TTS | ✗ checkpoints CC-BY-NC | excluded |
| XTTS-v2 | ✗ Coqui CPML | excluded |

### Excluded avatar stacks (license or quality)

- **HunyuanVideo-Avatar**: custom Tencent license (EU/UK/KR excluded, MAU cap) —
  third-party roundups claiming Apache-2.0 are WRONG.
- **LivePortrait**: MIT code but InsightFace dependency is non-commercial.
- **Sonic / Hallo3**: license chains not verified clean — excluded, not risked.
- **MuseTalk**: MIT but 256px mouth region reads soft at 1080p.
- **EchoMimic v3**: Apache-2.0, light, but a quality tier below — low-VRAM reserve.
- **Wan2.2-S2V-14B**: Apache-2.0 but same slow-14B economics; InfiniteTalk wins the slot.
- **daVinci-MagiHuman**: WATCHLIST — Apache-2.0 15B joint-AV specialist, but no
  external-audio input yet and ComfyUI support WIP. Re-evaluate ~Nov 2026.

### Riskiest assumption (the afternoon test that decides the lane)

That the **int8-quantized DISTILLED 8-step** LTX-2.5 transformer preserves
usable lip-sync from frozen external audio — official lipsync claims target the
full/two-stage recipes, and 2.5 has no official a2v template yet. Test: one 5s
clip (Chatterbox VO of a real product script → frozen-audio a2v with a
presenter image on the exact int8 distilled graph), judged frame-accurate at
1080x1920; comparison arms = same audio through LTX-2.3 int8 base and through a
LatentSync post-pass.

### The lanes compose

An avatar segment that flubs a word gets a **retake with frozen ORIGINAL audio**
(lane A machinery + lane B audio nodes) instead of a full re-render.

---

## Flags for the decision-maker

1. **LICENSE JUDGEMENT CALL**: LTX-2.x Community License (foundation of both
   lanes) is NOT OSI-permissive — free commercial use only under $10M/yr
   entity revenue; fine-tunes are non-transferable. It is the incumbent engine
   license (accepted 2026-08-18), treated here as "comparably unrestricted" —
   but confirm the client-revenue exposure question: whose revenue counts when
   reels are made for client brands?
2. **SPEC CONTRADICTION**: `MULTISHOT_MAX_PASS_FRAMES=481` ships marked
   "EMPIRICALLY UNVERIFIED" while the brief assumes 721-frame single passes —
   the bracket test result is unrecorded. Lane A unaffected (windows ≤241
   frames); full-reel wall-clock estimates depend on it.
3. Gateway integration for both lanes follows the existing sentinel /
   graph-surgery conventions (`models.py` mode literal + `comfy.py`
   `_render_*` + `workflows/*.json`), unit-testable without ComfyUI.
