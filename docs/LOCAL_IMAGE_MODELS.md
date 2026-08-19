# Local image models — the decision

**Decision, 2026-08-19: keep `gpt-image-2` as the default. No open-weights candidate is
ready to replace it today. Z-Image base 6B is the model to prove out, and the proving
run costs about half a GPU-hour. `LOCAL_IMAGES` stays `0`.**

This supersedes the earlier draft of this document, which named Z-Image the winner. That
conclusion is still the most likely *destination*, but it was reached on a number that
its own author explicitly warned should not be used for ranking. §7 says exactly where
this document disagrees with that draft and why.

---

## 1. Ranked recommendation

| # | Model | What to do with it |
|---|---|---|
| — | **`gpt-image-2` (incumbent)** | **Stays the default.** Nothing below it cleared the suite's `production_candidate` gate on a like-for-like clean comparison. |
| 1 | **Z-Image base 6B** (Tongyi-MAI) | **The candidate to prove out.** The only model whose headline failure was fully diagnosed *and* fully fixed by a change we have already shipped. Re-run it properly before flipping any flag. |
| 2 | **FLUX.2 [klein] 4B** (BFL) | **Branch-routed engine, never a hero renderer.** Top raw score and 10× the speed of anything else, but it hard-fails the placeholder branch and the prompt fix does *not* rescue it. |
| 3 | **Qwen-Image-2512** | **Reference point, do not ship.** Highest *verified* score on the clean suite, and the only model whose text failure is proven to be the model's and not ours. 20 GB and 86 s leave no room next to the video pipeline. |
| 4 | **HiDream-O1-Image (full)** | Reject as a hero. MIT and interesting, but it has the worst re-roll pathology measured anywhere (§4). |
| 5 | **Chroma1-HD** | Reject. Cleanest text behaviour of the large models, but hands collapse on 6 of 16 renders and 3 of 10 frames force the compositor's watermark fallback. |
| 6 | **HiDream-O1-Image-Dev** | Reject. Misses the shortlist bar outright. |

### Why "not yet" is the honest answer

Three models were scored on the corrected v1.1 suite with the protocol's four seeds, and
every verdict below survived a hostile independent re-score:

| Model | Median /40 | Publish rate | `production_candidate` needs 30.0 / 0.70 / artefact ≥3 everywhere | Result |
|---|---|---|---|---|
| Qwen-Image-2512 | **31.25** | **0.70** | numbers met, hard rule fails on P05 (1) and P10 (1) | shortlist |
| HiDream-O1 full | 28.375 | 0.60 | all three missed | shortlist |
| Chroma1-HD | 27.625 | 0.50 | all three missed; artefact rule fails on **four** prompts | shortlist |

Not one reached `production_candidate`. The two that came closest died on the same hard
rule — invented lettering — and §4 shows the app's text gate does not close that gap.
Shipping any of them today means roughly two client-facing images in ten carrying
invented text or a fabricated wordmark, with no reliable mechanism to catch them.

### Why Z-Image is nonetheless first

Because its failure is the one failure we can explain and have already fixed. Z-Image
was not failing on photography — it was reading the app's marketing brief as a *design*
brief and returning a finished poster: fabricated wordmarks, caption bars typesetting
the prompt's own Theme line, solid colour panels taking half the canvas. Two independent
agents removed the brand block, the literal hex codes and the "reserved for a brand logo
overlay" language, changed nothing else — same model, sampler, steps, seeds — and:

| Prompt | Before | After |
|---|---|---|
| P01 multi-person | 19.25 | 33.00 |
| P02 portrait | 24.75 | 36.75 |
| P04 ad + placeholder | 20.50 | 35.00 |
| P06 outdoor | 19.25 | 33.00 |
| P09 wellness + placeholder | 25.50 | 33.75 |
| **Suite median / publish** | **25.12 / 0.40** | **34.25 / 0.90** |

It also has the two properties the app actually depends on and no other candidate has
together: **the best negative-space discipline measured anywhere** (0 of 10 top-right
zones over the compositor's watermark threshold, against Qwen's 3 and Chroma's 5), and
**blank placeholder containers on both branches** — Qwen and Chroma each dropped the
container entirely on P09, and FLUX.2 printed a wordmark and a fake barcode on it. At
12.3 GB and ~37 s it is also the only candidate with genuine headroom on a 24 GB card
that is simultaneously running the LTX-2.5 reel pipeline.

**The caveat that keeps it at "prove out" rather than "ship":** that 34.25 is one seed
per prompt against the protocol's four, six frames re-rendered and four carried over
unverified, measured on a contended GPU, by the agent testing its own model. Its author
wrote the warning himself: *"Any ranking must re-run the other candidates on the fixed
prompt path before drawing a conclusion."* That warning is correct and this document
honours it.

### The measurement problem that dominates everything

Commit `8bab5cb` (2026-08-19 12:50) removed the brand name, the theme-as-subject line and
the overlay-intent language from the production image prompt. **Every scored run in this
document predates it**, and suite v1.1 still carries `Brand: Naturespan. Theme: …` and
`IMPORTANT COMPOSITION: … this area is reserved for a brand logo overlay`. v1.1 removed
the hex codes only.

So there are three prompt generations in play, and only one of them is what production
sends today:

| Prompt generation | Contains | Models measured on it |
|---|---|---|
| v1.0 | hex + brand + overlay language | Z-Image (25.12), FLUX.2-klein, Qwen (31.25) |
| v1.1 | brand + overlay language, no hex | Qwen 31.25, HiDream 28.375, Chroma 27.625 |
| **production today** | none of the three | **Z-Image only (34.25, single seed)** |

The rank order in the big table is therefore not trustworthy as a guide to production
behaviour. That single fact sets the entire test plan in §5.

---

## 2. Full comparison

| Model | Suite | Median /40 | Publish | Invented text on | Echoed text | Top-right zone over 2000 | s/image | VRAM | Licence | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **`gpt-image-2`** (reference) | — | calibrated 5/5/5 | — | none in 16 frames | none | 0/16 (range 2–1316, median ~76) | cloud | — | OpenAI commercial | incumbent |
| **Z-Image base 6B** bf16 | prod-today ¹ | **34.25** ¹ | **0.90** ¹ | P10 bottle label | none | **0/10** (max 1612) | **36.8** | 12.3 GB + 8 GB encoder | Apache-2.0, ungated | prove out |
| Z-Image base 6B bf16 | v1.0 | 25.12 | 0.40 | `PPONCLET` wordmark in the logo zone, leaf glyph | hex line, `Naturespan`, Theme line | 0/10 | 36.8 | as above | Apache-2.0 | — |
| **FLUX.2 [klein] 4B** bf16 | v1.0 | 34.25 ² | 0.90 ² (0.81 all-aspect) | P09 gibberish + fake barcode; P10 napkin | `Naturespan` on P09 | 1/10 (P08 fronds) | **8.1** | 17.0 GB | Apache-2.0, ungated | branch-route only |
| **Qwen-Image-2512** fp8 | **v1.1** | **31.25** ³ | **0.70** ³ | P05 chalk sign + shelf tags, P10 bottle labels | **0** | 3/10 (P05 2003, P06 4159, P08 3646) | 86.4 | 23.7 GB peak, ~12 GB own | Apache-2.0, ungated | shortlist |
| **HiDream-O1-Image** fp8 | **v1.1** | **28.375** ³ | **0.60** ³ | P01 shopfront, P04 pouch, P05 price card | P01, P04 (brand + theme strings) | — | ~103–109 best | contaminated | MIT, ungated | shortlist |
| **Chroma1-HD** 8.9B fp8 | **v1.1** | **27.625** ³ | **0.50** ³ | P01 crate label, P01-sweep apron wordmark | **0** | 5/10, 3/10 both corners | 68.9 (contended) | ~8.9 GB UNet | Apache-2.0, ungated | shortlist |
| HiDream-O1-Image-Dev fp8 | v1.0 | 23.1 | 0.40 | placeholder text | — | — | 13.0 | 10.5 GB | MIT, ungated | reject |

¹ Single seed per prompt, six frames re-rendered under the fixed prompt and four carried
over. Indicative, not settled. ² Self-reported, not independently re-scored; P01 is
marked publishable despite a merged four-hand knot and a mis-scaled child's leg, which
reads like a miss against the gate's anatomy clause. ³ Adversarially verified — an
independent agent set out to refute each and these are the numbers that survived. Qwen's
were confirmed outright; Chroma's were revised down from 29.125/0.60 and HiDream's from
30.13/0.70.

Every candidate cleared the licence gate. **Licence is not a discriminator in this
bake-off** — see §6.

---

## 3. The `gpt-image-2` delta, concretely

What is actually lost by going local, in order of how much it costs the product.

**1 — Overlay-safe negative space. This is the widest and most consistent gap, and it is
a hard product requirement rather than an aesthetic one.** `image_processing.py` falls
back to an ugly watermark logo when the top-corner luminance variance exceeds 2000. The
16 gold-reference raws measure 2–1316 on that crop, median ~76. Qwen measures 140–4141
and breaches on 3 of 10 — and on P06 the top-*left* fallback breaches too (3298), so that
frame forces the watermark path outright. Chroma breaches on 5 of 10 with both corners
gone on 3. Z-Image is the exception and breaches on none. Concretely: with Qwen or
Chroma, roughly a third of posts come back with the wrong logo treatment.

**2 — Text discipline.** The 16 gold frames carry *zero* rendered text, and they were
generated from briefs stuffed with brand names, supplier names, certification marks (AB,
Ecocert, Eurofeuille), a URL (`shop.naturespan.mu`) and a price (Rs 2,000). `gpt-image-2`
refused all of it and left typography to the compositor. Every open-weights candidate
rendered at least one invented mark. *Honest counterweight:* the gold set is not
flawless — a live `gpt-image-2` production post carries hallucinated garbled French on
product packaging. The gap is large but it is not perfection versus failure.

**3 — Placeholder discipline.** The Gemini product-swap depends on a genuinely blank
container. `gpt-image-2` delivers one. Qwen and Chroma both dropped it entirely on P09.
FLUX.2 rendered a legible `Naturespan` wordmark, gibberish body copy and a fake barcode
on it — and the brand-strip probe did **not** fix that, because the trigger is the
concept "product container", not the brand string.

**4 — Casting.** The gold set is specifically Mauritian Creole and Indian, ages spread
~5 to ~55. Every candidate, Z-Image included, drifts to White European wherever the
prompt does not name an ethnicity, and sometimes where it does. This is brand fit, not
an artefact, and it does not show up in the numbers.

**5 — Skin at full-figure distance.** Gold ref holds pore structure and flyaway hair at
any distance. Every candidate flattens to a generic AI-stock look on full-length shots
(P08). Close and mid-range skin is at parity — Z-Image's P02 portrait and Qwen's P09 face
are genuinely indistinguishable from the reference at 100%.

**6 — Hands in contact.** Hand-to-hand and hand-to-object contact is the top structural
failure class. Chroma fails on 6 of 16 renders. FLUX.2 merges the four-hand cluster on
P01 and P10. Isolated hands render beautifully everywhere; it is specifically contact
that collapses. No text gate can see this.

**What is *not* lost.** Still life, macro and material realism are at or above the
`full_replacement` line for essentially every candidate — the flat-lay and macro prompts
scored 35.5–38.0 across the board, with individually resolved grains, correct water
refraction and real wood grain. Mixed-colour-temperature lighting (daylight vs tungsten,
candle vs dusk) is handled honestly by Qwen, Chroma and Z-Image rather than white-balanced
away. **These frames carry no brand block, no people and no placeholder — and they are
the one part of the mix that could go local today with no measured risk.**

---

## 4. What the text gate changes: almost nothing, and it is currently broken

Three separate studies ran the real `agents/shared/image_text_guard.py` — unmodified
detector, real production vision model, `allowed_text=None` matching all three call
sites, real `strengthen_prompt()` re-rolls through the forge.

**Detection.**

| Model | Human-flagged frames | Caught | Missed | False positives |
|---|---|---|---|---|
| Qwen-Image-2512 | 2 | 1 (intermittently) | 1 | 0 / 20 clean checks |
| Chroma1-HD | 2 | 1 | 1 — **the scored frame that counted** | 0 / 23 clean checks |
| HiDream-O1 full | 2 | 2 | 0 | 0 / 24 clean checks |

On a single pass over Qwen's whole ten-frame suite the gate flagged **zero** images,
including both known-defective ones. Its per-check catch rate on the two bad frames is
2/12 = 17%.

**The root cause is a prompt-design defect in the guard, not a limit of the vision model.**
`_TEXT_GUARD_PROMPT` asks only about "each piece of lettering you can read", requires it
"transcribed verbatim", and explicitly excuses "texture at extreme background blur where
no letter shape can be resolved". `verdict_from_payload` flags only when a transcription
field is non-empty. Lettering with no resolvable glyphs has nowhere to be reported — and
every one of Qwen's five invented-text instances is recorded as *"none resolvable"*. More
pixels do not help: on native-resolution crops P10 still flagged 0/4. A diagnostic probe
that named un-transcribable letterform structure as the defect flagged 3/10 — P01, P05,
P10, exactly where the human found them — with zero clear false positives. **The vision
model sees it perfectly well once the prompt lets it say so.**

**Re-rolls make things worse more often than better.**

- HiDream P04: flagged on all three attempts, severity **3 → 7 → 10**. Attempt 3 typeset
  the guard's own rejection list onto the pouch — `Cartified-Pantry / IRADDIES BLUDGE /
  Certified Organic / Premium`. Zero of two recovered.
- Qwen P05: severity **1 → 1 → 4**. The escalation instruction ("remove printed-surface
  props altogether") produced chalk shelf tags reading `basil`, `dill`, `thyme` and a
  euro symbol. On exhaustion the loop republishes the *original* frame — three renders
  spent to ship the frame it started with. (Severity is `len(offending)` with a strict
  `<` tie-break, so a re-roll can never win a tie.)
- Qwen P10 *was* cleanly fixed in two renders — but the gate never fires on it, so
  production would never re-roll it.

**Gate-adjusted publish rate: Qwen 0.70 → 0.70. HiDream unchanged. Chroma unchanged.
Not one model moved.**

**Cost is not the objection.** ~1.03 renders per image expected, ~+3–6% GPU, ~4.5 s of
vision per image. The objection is that two in ten published images still carry invented
lettering with the gate on.

**Two independent agents found the same live production bug.** `detect_unintended_text`
hard-codes `"temperature": 0`. `gpt-5.6-sol` rejects it — HTTP 400, *"Unsupported value:
'temperature' does not support 0 with this model"*. In production this survives only
because `litellm/config.yaml` sets `drop_params: true`, which silently strips it. Point
`IMAGE_TEXT_GUARD_MODEL` at a provider directly, or turn `drop_params` off, and **the gate
stops guarding every image while appearing configured and enabled**, logging nothing but
a warning. Because the parameter is dropped rather than honoured, the detector also runs
at temperature 1 and is non-deterministic, so single-sample gate results are not
trustworthy. The 40 unit tests pass against a detector that misses the defect it exists
to catch, because the vision responses are stubbed.

**Net effect on the decision.** The gate is *necessary* — even `gpt-image-2` needs it, as
the garbled French on a live production post shows — but it is *not sufficient*, and it
must not be cited as the mitigation for any model's text behaviour. Even with the
pseudo-text branch fixed, on Qwen it changes the outcome from "ships defects silently" to
"burns GPU and then ships them": best case ~0.80 publish with the hard rule still failing.
Fixing it is worth doing on its own merits, for every model including the incumbent. It
does not promote anybody.

---

## 5. What to test next, ranked by information per GPU hour

The whole plan below is about **3.5 GPU-hours**. That is the strongest argument for not
deciding anything permanent today.

| # | Test | GPU cost | What it settles |
|---|---|---|---|
| **1** | **FLUX.2-klein-4B, 10 prompts × 4 seeds, on today's post-`8bab5cb` prompt** | **~5 min** | At 8.1 s/image this is free information. It already posted the top raw median. Settles whether the P09 placeholder label survives the prompt fix — the brand-strip probe says it does, which would permanently confine FLUX.2 to the no-placeholder branches. |
| **2** | **Z-Image base, 10 prompts × 4 seeds, today's prompt, quiet GPU** | **~25 min** | **The run the entire recommendation hangs on.** Converts a single-seed 34.25 into a real number and gives the first clean VRAM and s/image figures. If it holds ≥30 / ≥0.70 with artefact ≥3 everywhere, flip the default for lifestyle. |
| **3** | **Fix the guard: pseudo-text branch in `_TEXT_GUARD_PROMPT`; drop the hard-coded `temperature: 0`; add one end-to-end test on a real pseudo-text frame** | **0** | Pure code, already validated at 3/10 flagged with no clear false positives. Closes a silent fail-open that affects `gpt-image-2` today, not just local models. Do this regardless of which model wins. |
| **4** | **Qwen-Image-2512, 4 seeds, today's prompt** | ~1 h | The only *falsification* run here. Qwen invented text on v1.1 with nothing to echo, at CFG 4 and 5, so the prompt fix probably will not help — but it holds the highest verified score and it is the one number that survived a hostile re-score. Skip it if 1 and 2 come back clean. |
| **5** | **Branch-routing probe: FLUX.2 on ad/no-placeholder, Z-Image on lifestyle + placeholder** | ~15 min | The ad branch is ~half of production volume and is the easy case. If FLUX.2 holds it at 8 s/image, half the mix goes local at negligible cost. |
| **6** | **Hand-contact stress set — P01/P08/P10 geometry, 8 seeds, top two models** | ~30 min | Hands are the #1 structural failure and the gate is blind to them. Four seeds across ten prompts under-samples the one defect no downstream check can catch. |
| **7** | **Casting: physical descriptors per subject instead of a nationality label, 3 prompts × 4 seeds** | ~20 min | Every model drifts European. Try the free prompt-side fix before anyone budgets a LoRA. |
| **8** | **Palette as materials — "olive-green glazed ceramic", "sand linen" rather than a colour rule** | ~15 min | The remaining half of the prompt-hygiene work. Colour compliance is the weakest axis on the leading candidate. |
| — | Chroma / HiDream re-runs | ~2 h | Low value. Both are behind on the clean suite *and* have failure modes the prompt fix does not touch. |
| — | Casting LoRA or any finetune | weeks | Last resort. Only after 7 leaves residual drift. |

---

## 6. Licence position — Z-Image base

**Apache-2.0, ungated.** <https://huggingface.co/Tongyi-MAI/Z-Image>

Apache-2.0 on the upstream Tongyi-MAI repositories and on the Comfy-Org repack, and on
all three components in use: the 6B transformer, the Qwen3-4B text encoder and the VAE.
No acceptance click, no gate, no revenue cap, no share-alike, no downstream-open-sourcing
clause, no content-filter obligation, and no clause claiming any right over generated
output.

**Permits:** unrestricted commercial use including generating images for paying clients,
modification, redistribution, and running the weights as a hosted service.
**Obliges:** the ordinary Apache-2.0 terms — ship the `LICENSE`/`NOTICE` files with any
redistribution of the *weights*, and state significant modifications. Generated images
carry no licence obligation and no attribution requirement. No LoRA is in use, so no
per-model Civitai permission flag applies.

**Every model in the bake-off cleared the licence gate** — four Apache-2.0, two MIT, all
ungated. Licence did not eliminate a single candidate and should not be presented as a
reason for the choice. Note only that FLUX.2 [klein] **4B** is the Apache-licensed tier;
its 9B sibling is not, and was deliberately not tested. `gpt-image-2` continues under
OpenAI's commercial terms as today, unchanged.

---

## 7. What would change this recommendation

The honest weakness in this document is that I am ranking Z-Image first on a number its
own author told us not to rank on: one seed per prompt instead of four, six frames
re-rendered under a prompt change with four carried over unverified, on a GPU shared with
a live reel render, scored by the agent testing its own model. The only number here that
survived a deliberate attempt to refute it is Qwen's 31.25 — and Qwen's text invention was
*proven* not to be our bug, reproducing identically across two prompt versions, two CFG
values and a re-roll that made it worse. If I weighted methodological rigour above
headline score, Qwen would rank first, and because Qwen cannot be fixed by anything short
of a finetune, the answer would harden to "stay on `gpt-image-2`, full stop". So: if test
2 reproduces ≥30 median / ≥0.70 publish with artefact ≥3 on every prompt across four
seeds, flip the lifestyle branch to local immediately and this becomes a straightforward
win. If it comes back materially below that — if the 34.25 was a lucky seed — then the
recommendation is not "try the next model down the list", it is "stay on `gpt-image-2`
indefinitely", because Z-Image was the only candidate whose failure we had a proven fix
for and the rest are further away on a suite that already flatters them. One more thing
would change it in the other direction: if the guard's pseudo-text branch (test 3), once
shipped, turns out to catch un-transcribable lettering at high recall *and* a re-roll
against a **different model** rather than the same one converts those catches into clean
frames, then the residual text risk stops being a blocker for the whole class and the bar
drops for everybody — including Qwen.

---

## 8. How the local path works (already wired, off by default)

```text
agents container                      GPU box (Windows, RTX 4090)
─────────────────                     ────────────────────────────
generate_image(prompt, size)
  │  shared/llm.py
  ├─ LOCAL_IMAGES on? ──yes──▶ POST {VIDEO_FORGE_URL}/v1/images ─┐  Video Forge
  │                            GET  /v1/images/{id} (poll)       │  FastAPI gateway
  │                            GET  /v1/images/{id}/result       │  127.0.0.1:9100
  │                           ◀── PNG bytes ────────────────────┘        │
  │                                                            one SQLite queue,
  │                                                            one worker
  │                                                                      ▼
  │                                                        headless ComfyUI :8188
  ├─ on ANY local failure ──▶ existing cloud cascade
  │                          (active image model → per-channel fallback → gpt-image-1)
  ▼
shared/image_text_guard.py  ── vision check + re-roll (see §4 for what it actually catches)
```

- **`LOCAL_IMAGES` is unset/`0`. Nothing changes until it is flipped, and it should stay
  off until test 2 in §5 has run.**
- The agents container never names a model. The request carries prompt, aspect and count;
  the *gateway* resolves the workflow from its own `IMAGE_PRESET`. Swapping the local
  model is an ops change on the GPU box — no agents redeploy.
- Sizes map to the same canvases `gpt-image-2` renders (`1024x1024` → 1:1, `1536x1024` →
  3:2, `1024x1536`/`1024x1792` → 2:3), so switching changes no crop.
- Every local failure falls through to the cloud cascade with a `WARNING` naming the
  cause. Worst case of enabling the flag is a *slower* image, never a missing one.
- Bypassed even when on: an explicit `model=` argument, and `category="image-edit"` (the
  Gemini product-swap path is untouched — no local edit model has been benchmarked).
- The card is shared with the LTX-2.5 reel pipeline (20 GB transformer + 14.3 GB encoder).
  The gateway serializes both job kinds through one queue and one worker; two renders on
  the card at once is what OOMs 24 GB. The app must go through `:9100` and never drive
  ComfyUI on `:8188` directly.
- **Every VRAM and wall-clock figure in the bake-off is contaminated** by concurrent reel
  rendering and other agents queueing through the same FIFO. Treat them as upper bounds.
  Clean re-measurement is part of test 2.

### What still needs a cloud model

| Path | Provider | Why |
|---|---|---|
| All post images | `gpt-image-2` | Default. This decision. |
| Product swap / image editing | Gemini `image-edit` | No local edit model benchmarked. |
| Text-guard vision check | active `vision` model | It is a VLM inspection, not a render. |
| Any frame a future local path fails | cascade → `gpt-image-1` | Deliberate, not vestigial. |

---

## 9. Files

| | |
|---|---|
| `agents/shared/llm.py` | `local_images_enabled()`, `_generate_image_local_forge()`, cascade position 0 |
| `agents/shared/image_text_guard.py` | the reject-and-reroll gate — see §4 for its two open defects |
| `agents/workflows/content/nodes.py` | `generate_background` — prompt assembly; the `8bab5cb` fix lives here |
| `markai-video-forge/benchmark/suite_v1.1.json` | rubric, thresholds, the ten prompts (still pre-`8bab5cb`) |
| `markai-video-forge/benchmark/goldref/` | the 16 `gpt-image-2` reference frames + manifest |
| `markai-video-forge/benchmark/results/*.json` | per-slot scores; `*_gate.json` are the text-gate studies |
| `markai-video-forge/workflows/img_*.json` | one ComfyUI graph per candidate |
