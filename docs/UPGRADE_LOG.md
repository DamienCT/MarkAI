# Upgrade–Audit Loop Log

Companion to [MASTER_UPGRADE_SPEC.md](MASTER_UPGRADE_SPEC.md). One entry per QA/upgrade cycle
(spec mandates ≥5, ≤15 cycles, stop at diminishing returns). Each entry: what was audited,
what was found, what was changed, and verification.

---

## Cycle 1 — Naturespan context-generation QA (2026-08-18)

**Scope audited:** the full auto-generated context chain for the first production brand
activation (Naturespan): research → strategy → planning → 624-item / 52-week calendar,
plus a read-only audit of the generated rows in the production DB.

**Method:** 3 parallel reviewers (research+strategy vs brand brief, planning+campaigns,
calendar DB audit) → every blocking finding adversarially re-verified by an independent
agent. 17/17 blocking findings upheld, 0 refuted.

### Findings (blocking)

| # | Severity | Finding |
|---|----------|---------|
| 1 | critical | "Healthy Made Affordable" pillar (15% of all content) institutionalizes the forbidden affordability/cheap-pricing angle across 11 of 12 months |
| 2 | critical | Festival dates factually wrong (Diwali off by 2 weeks, Eid off by a month, CNY/Ganesh Chaturthi wrong years' dates; fabricated "Emancipation Day Aug 1") |
| 3 | critical | Sept 1 Grand Baie + Tamarin store openings absent from ALL layers — strategy, planning, and every one of the 624 calendar items |
| 4 | high | Trust pillar invites company-level certification claims (only the *products* are certified) |
| 5 | high | Identity drift: strategy treats the grocery retailer as a packaged-goods brand |
| 6 | high | Non-enabled channels (TikTok, Google Search) embedded as strategic dependencies |
| 7 | high | ~10% of calendar items push "affordable/budget" messaging; 9 items script "supermarket" visits |
| 8 | high | Calendar entirely brand-agnostic: zero mentions of organic, certification, brand name, suppliers, e-shop |
| 9 | high | Timezone bug: "evening 20:00" slots stored as 20:00 UTC = 00:00 Mauritius — 243 posts land around midnight |

### Root causes (all in the generators, not the LLM's mood)

1. **No grounding injection**: strategy nodes received only research data — never the brand's
   name/description, tone, `dos`/`donts` guardrails, or enabled channels
   (`agents/workflows/strategy/nodes.py`); planning prompts likewise lacked identity + guardrails.
   (The *content* workflow already injected dos/donts — the gap was strategy + planning only.)
2. **Hallucinated dates by design**: `generate_themes` asked the LLM to produce `key_dates`
   "covering relevant holidays" from memory, ungrounded.
3. **Poisoned events table**: the AI event detector stores unverified LLM dates with
   `is_annual=true`; movable lunar holidays shift ~11 days/year, so annual projection is
   inherently wrong — and the detected dates were from wrong years to begin with.
4. **Local-vs-UTC**: `store_calendar_items` stamped naive brand-local datetimes with
   `tzinfo=UTC` (`agents/shared/tools/database.py`).
5. **Store openings unrepresentable**: brand-milestone dates lived only in prose
   (brand description), which planning ignores; the events table had no rows for them.

### Remediation (this cycle)

- New `agents/shared/brand_context.py`: single grounding block (identity + hard guardrails +
  enabled channels + never-invent-dates rule) injected into every strategy and planning LLM call.
- `get_brand_config` extended to select `name`, `slug`, `description`.
- Strategy `generate_themes` grounded in the events table (same source planning uses);
  key_dates restricted to listed events only.
- Research summary hardened against fabricated analytics claims.
- `store_calendar_items` converts brand-local times (default `Indian/Mauritius`) to UTC.
- Event detector: movable holidays forced `is_annual=false`, year-explicit dates, omit-if-unsure.
- Events table repaired from a **web-verified** Mauritius 2026–2027 holiday calendar
  (official sources; movable dates never taken from LLM memory), plus brand-milestone events
  for the Sept 1, 2026 Grand Baie + Tamarin store openings and countdown week.
- Naturespan strategy → planning chain re-run after deploy; context re-QA'd before approval.

**Verification:** adversarial review of the combined diff + full backend test suite green +
re-QA of regenerated context docs (cycle 2 entry will record the re-QA result).

Also shipped alongside this cycle (separate commit `54897e0`): direct in-backend publishers
for IG/FB Reels, YouTube Shorts, LinkedIn video — that workflow's review caught 2 critical
integration breaks (registry pointing at nonexistent modules; YouTube/LinkedIn missing the
dispatch seam) before they reached production.

---

## Cycle 2 — Regenerated context re-QA (2026-08-18/19)

**Scope:** the Naturespan context regenerated on the fixed pipeline (strategy `13 themes`,
full-horizon replan, 624 items), same 3-reviewer + adversarial-verify setup as cycle 1.

**Result: all 8 cycle-1 defect classes confirmed FIXED** by every reviewer independently —
premium pillars (no affordability angle), all 24 dated key_dates matching the verified events
table exactly, the Sept 1 openings carried by a dedicated 20%-weight pillar + countdown
(Aug 23–31, all channels) + opening-week coverage, product-level certification phrasing
throughout, retailer identity restored, IG/FB/YouTube only, dense verified proof points,
and every one of 624 items scheduled 06:30–21:00 Mauritius local. 0 findings refuted.

**Remaining findings and dispositions:**
- *Stale pre-opening framing on 19 post-opening items* (high) — fixed by SQL: de-anticipated
  phrasing; Aug-2027 "Countdown…" cluster retitled to anniversary framing. Generator-side
  temporal check (no anticipatory language after an event's date) queued for cycle 3.
- *Guardrail-9 drift* ("20+ years expertise **through ACCORD BIO**", medium) — fixed by SQL in
  8 stored payloads; correct phrasing lives in the (now accented) guidelines the content
  generator reads.
- *"Mauritius Health Week" flagged as fabricated* — FALSE ALARM: it is a legacy **manual global**
  events row (2026-05-11→27, annual) the reviewers' brand-filtered query missed; the planner
  obeyed its date rules. Authenticity of the event itself is a user question (possibly a
  Chemtech-organized initiative).
- *campaigns output truncated/unparseable* (critical, planning `campaigns.json`) — real
  generator defect (campaigns wrapped as escaped JSON in one record + token truncation; June/
  July 2027 campaigns missing). Does not affect the 2-week window. **Cycle-3 backlog**: chunked
  campaign generation + parse-and-count validation gate.
- *French diacritics stripped* (medium ×3) — root cause: the onboarding guidelines were written
  accent-free and the grounding block propagated that. Fixed at the source: brand description,
  tone_of_voice, and all guidelines strings re-accented in the DB; future generations inherit.
- Other non-blocking (cycle-3 backlog): proof-point repetition damping (+69% stat 28×/year),
  generator meta-language leaking into 106 briefs, theme-title reuse (350/624), provisional
  2027 holiday-date contingency handling.

**Approved & launched:** all four context docs approved (`first_approval_completed=true`);
25-item Aug 18 → Sep 1 batch queued and generating sequentially (posts + reels; reels render
on the local RTX 4090 via LTX-2.5 — see D:\markai-video-forge, live as of this cycle:
3s 1080×1920 H.264+AAC in 24s wall).

---

## Cycle 3 — Batch delivery + multi-shot reels (2026-08-18/19)

**Batch result: 25/25 generated, 0 failures.** 16 posts (branded images verified) + 9 reels
(videos byte-verified in MinIO, 2.4–4.8 MB each, rendered on the local 4090 at $0.00 marginal
cost). Final inline audit across all items: 0 guardrail violations (after fixes below),
0 hashtag overruns, accents present, every slot 06:30–21:00 Mauritius local, no duplicate
(channel, time) slots, Sept 1 opening covered on all 3 channels, 13 countdown items Aug 23–31.

**Mid-batch corrections (feedback loop in action):**
- First two captions spoke as *je/moi* → 2 new hard guardrails added to brand_guidelines
  (nous/on voice; ≤5 hashtags, never hashtag pillar names) — every later item complied.
  The 3 pre-patch captions were hand-rewritten to brand voice (worker correctly refuses
  `content.generate` on in_review items — editor-style SQL rewrite was the right tool).
- One truncated pillar-name hashtag (`#WellnessWith`) removed.

**Multi-shot reel engine shipped (`de851f5`, deployed post-batch):** per-shot provider calls
(shot 1 i2v from branded keyframe; shots 2..N i2v chained from the previous shot's last frame),
duration fitter (3–5s clamp, 20–35s target), master-spec normalization for non-forge shots,
same-encoder-only stream-copy concat (else re-encode), per-shot progress windows, aggregated
cost/ledger. Review found 6 issues (mixed-encoder copy-concat, `-shortest` truncation,
ffprobe gating, Veo snap drift, reel-length floor, partial-spend surfacing) — all fixed;
agents suite 97 passed. Current-batch reels are single-shot ~5s (rendered pre-upgrade);
future reels render 20–30s.

**Cycle-4+ backlog:** campaigns-JSON truncation fix + validation gate, generator-side temporal
check, proof-point repetition damping, meta-language leak in briefs, franglais tuning,
planner MAX_SHOTS=6 (35s top end unreachable), "Mauritius Health Week" authenticity (user),
n8n workflow re-import, observability, token encryption, engagement 2.0, Qdrant learning loop.

---

## Cycle 4 — 30s reels, campaign integrity, English-only enforcement (2026-08-19)

**Shipped (`c68ef5b`, deployed):**
- **30s reel targeting.** Reels now plan 6–8 beats against `TARGET_TOTAL_S = 30.0` instead of
  a single ~5s clip. `MIN_PLAN_SHOTS=6` guarantees the fitter can reach the target; 6–10 beats
  land exactly on 30.0s. First validated render: **7 shots, 30.00s, all on the local 4090 via
  forge at $0.0000**.
- **Render budgets unified.** `shared/config.video_workflow_timeout_s()` is now the single
  source for both the worker's `asyncio.wait_for` and JetStream's `ack_wait`, so they cannot
  drift. `video.render` gets its own hours-long ack_wait (25620s) while the other subjects keep
  the short one (5520s) — previously the long video budget was applied to *every* subject,
  which would have left a planning message unredelivered for hours after a worker died.
  JetStream does not always re-apply a changed `ack_wait` to an existing durable, so the
  consumer now reports drift; both durables were verified live at the new values.
- **Campaign integrity.** Campaigns and the strategy document are generated in quarterly chunks
  behind a post-assembly validation gate. The raw-string fallback that produced the
  "General Campaign" blob is deleted — corrupt output now fails the node loudly rather than
  persisting a truncated array as one campaign.
- **Brief hygiene + temporal guard.** Generator meta-language ("This post should…") is scrubbed
  before the brief reaches the writer; a temporal block tells the hook which listed events are
  already past on its own publish date.

**Bugs found and fixed:**
- `_release_stuck_calendar_item` used `:reason::text`. SQLAlchemy's bind-param regex has a
  negative lookahead on `:`, so `:reason` was never bound and the literal shipped to Postgres,
  killing every release attempt on a syntax error. **Consequence: any item whose workflow died
  stranded in `working`/`rendering` forever.** Fixed with `CAST(:reason AS text)`; swept the
  codebase for the same pattern (no other occurrences).
- **The reverse SSH tunnel was down**, so the VPS could not reach the 4090 and every reel
  render failed with `forge: unavailable; fal: unavailable` while the forge was healthy
  locally. Restarted, and `MarkAIForge-{ComfyUI,Gateway,Tunnel}` are now registered as
  scheduled tasks so it survives a logon.

**QA findings on the live review queue (Naturespan, 24 items):**
- 16 posts are clean English; the 8 reels were French **and** 5.01s single-shot — they predate
  both fixes and are being re-rendered.
- `content.image_urls` is a dead column. Post images live at
  `generation_metadata->>'generated_image_url'`, which is what the frontend reads. Anything
  auditing "posts with images" against `image_urls` will report a false zero.
- Image quality is genuinely mixed and is the next cycle's focus: the family/lagoon and
  Pranarom-bottle frames are publishable, but one frame is empty set-dressing with the dark
  wordmark placed on a dark shadow band, and the Favrichon frame has the headline overflowing
  the right edge across the product plus **hallucinated garbled French** on the packaging.
  That last one is gpt-image-2 output — the gold standard hallucinates text too, which is why
  the fix is an app-level reject-and-retry gate rather than a model swap.

**Local image models (bake-off slot 1):** Qwen/Qwen-Image-2512, Apache-2.0, ~86s per
1024×1536 render, 23.7 GB peak. Median weighted 31.25, publish rate 0.70 — both numeric bars
met, but **SHORTLIST not production**: it fails the hard rule `ai_artefact_absence >= 3 on
every prompt` by rendering gibberish labels on props (P05, P10). cfg 5.0 did not suppress it.
Being the best open-weights *text* renderer is precisely why it invents text. Slot 2 candidates
and the text-reject gate are in flight.

**Cycle-5 backlog:** logo variant/contrast selection against the region actually chosen,
headline overflow + product occlusion, empty-frame briefs, hallucinated-text gate rollout,
n8n workflow re-import, observability, token encryption, engagement 2.0, Qdrant learning loop,
"Mauritius Health Week" authenticity (user).

---

## Cycle 5 — Image quality: why the pictures were wrong (2026-08-19)

Every `in_review` post across all three brands was vision-audited and re-checked
by hand (`AUDIT_ARTIFACTS/image_qa_*.md`): **Naturespan 4/16 clean, Healthspan
6/13, FancyFinds 4/10.** 51 defects, and they collapse into a small number of
causes — most of them not where they appeared to be.

**Hallucinated text (14 defects) does not come from the image generator.**
`background.png` is clean — the negative directive works. The invented lettering
appears in `composed.png`, i.e. it is introduced by the Gemini product-swap step
(`_replace_product_in_generated_image`), which is a *generative* editor and
re-synthesises every pixel of the pack including its printed copy. On one item it
also turned one pouch into four. The prompt carried no "this is a copy job"
contract, and the reference is starved — the pack's body copy is ~8px tall in an
800×800 catalogue JPEG. Verbatim output: `Une recette croortillante an blé
fomgnis`, `RICHE ao FER MACROUOM ur PHOESNORE`, `1B%ARA&BICA`.

**Half of every brand's posts were photographed from a five-word campaign label.**
`generate_background` branched on `image_format == "ad"` FIRST, so an ad post's
prompt was built from `calendar_items.theme` alone — both the art-director's
enhanced prompt and the planner's brief were discarded. `_decide_image_format()`
picks "ad" ~50% of the time globally. A brief asking for "a sharing board — crisp
toasts, olives, and cheese" delivered chocolate chunks and cashews, because the
model was given "Indulgent Everyday Pairings & Social Treat Moments" and nothing
else. `visual_direction` was written by the planner on every row and read by
nothing; `brand_guidelines.donts` reached every copy prompt and no image prompt.

**Empty frames were what the prompt asked for.** `image_format == "ad"` AND no
`product_ids` took an else-arm ending in the literal instruction *"Do NOT include
any products. Focus on a clean branded backdrop."* With no product there is
nothing else to show, so the backdrop IS the picture. That combination predicted
all 5 empty frames with 100% precision and recall. Aggravated by 4 of 5 briefs
being reel scripts ("montage of shelf details…") that a still model cannot render.

**Logo illegibility had two compounding faults.** Naturespan carried only a
`primary` (dark-ink) logo — no light variant — so `select_logo_variant`, whose
entire job is to return a light logo when the region is dark, had nothing to
return; all 16 items recorded `logo_variant_used='primary'`. And
`review_branding` returned early for every ad-format post, which are exactly the
posts where the art-director LLM places the logo at the bottom of the frame.
Measured: the three failures are 2.15:1, 2.69:1 and 1.82:1 while every scanned
top-corner placement measures 4.5–7.5:1. On "One week to shop with ease" the
background under the wordmark swings 1.82–7.72:1 — it was placed on the least
uniform band in the frame (spread 5.91) while the calm pale wall (3.43) went
unused. **No clipping defects exist in this batch** — an earlier by-eye call of
mine was wrong and every margin was re-measured.

**Fixed:** the text-reject gate (`shared/image_text_guard.py`) at the single
`generate_image` choke point; hex removed from image prompts
(`shared/color_names.py`); WCAG contrast measurement replacing the ad-post skip,
scoring the logo ink's *10th-percentile* contrast against the patch it covers;
a light Naturespan logo generated and registered; product backfill taking
Naturespan planned coverage 0% → 91%, which is also the empty-frame fix.

**Healthspan data defects fixed:** `category_logos['SUP-TOOLS']` held the
Healthspan logo itself, so every SUP-TOOLS post composited the brand mark twice
in opposite corners — entry removed. The REUS-WEAR (RingConn) and DISP-WEAR
(SIBIONICS) "dark" variants were **knockouts**, not artwork: an opaque black
plate with the mark punched out as transparency, which paints a black plaque on a
photo. Both inverted to white ink on transparency; originals kept as
`*-knockout.png`.

**Healthspan has 0 products and 456 dangling `product_ids` — root cause found,
needs a decision.** Its `bc_company` is `Barcode.mu`, and that company has
**3140 item-ledger rows of which ZERO have positive `remainingQuantity`** (sum
0.0, max 0.0). `get_active_stock` gates on `SUM(remainingQuantity) > 0`, so the
sync returns nothing. Every other trading company has real stock (Naturespan
1182 positive rows, Food-Cosmetic 1988, Medical-Ortho 9037). Separately there IS
a BC company literally named `Healthspan` with 31 items and 78 positive rows.
Open question for the user: is Barcode.mu genuinely out of stock / not
inventory-tracked, should the brand point at the `Healthspan` company, or should
the stock gate be relaxed for catalogue-only brands?

**Flagged, not fixed:** the generator prints "Healthspan" onto the blood-pressure
monitors themselves — an implied own-brand claim for a retailer. That is a
brand/legal question, not a rendering bug.

**Cycle-6 backlog:** product-swap lettering contract (the biggest remaining
defect class), logo/headline collision on 1536×1024, `visual_direction` validated
against `item_type` at planning time, n8n workflow import (the instance has zero
workflows), observability, token encryption, Qdrant learning loop.

## Cycle 6 — 2026-08-19

**Healthspan repointed and re-catalogued.** The user chose the `Healthspan` BC
company. Its items carry an **empty `itemCategoryCode` and mostly empty
`vendorNo`**, so the Barcode.mu-era vendor/category filters would have zeroed it
out a second time; they were cleared and `ALBION` added to the locations.
`sync_bc_products()` produced 28 products. Six heroes are active and 22
RingConn size/colour variants stay inactive — but the first pass activated the
*Counter Display Unit* and the *Ring Sizing Kit* rather than a ring, because the
variant regex stripped `, Size 10 Black` and the display unit formed its own
family. Corrected: a real ring is the hero, the retail fixture is not.

The 456 dangling `product_ids` were dangling because the sync replaced the
catalogue outright. 488 items were re-attached by **health signal** (glucose,
blood pressure, temperature, sleep) rather than by supplier brand word, which is
how Naturespan's backfill works — Healthspan's copy names the *signal*, not the
supplier. 188 awareness items were deliberately left product-free: attaching a
sensor to "three practical signals caregivers can monitor" puts a product claim
into a post that is not making one.

This also resolves the item flagged in cycle 5. The generator printing
"Healthspan" onto a blood-pressure monitor is **not** an implied own-brand
claim: the BC catalogue names them `Healthspan, Digital Upper Arm Blood Pressure
Monitor, Model D5819`. It is their private label.

**English enforcement rebuilt after French shipped to customers.** Five
Naturespan calendar items and 32 content rows came back in French; one reel was
mid-render with a French CTA burned onto the master. The root cause was not the
prompt. The **brand record instructed French**: `dos[1]` licensed "the French
term magasin bio", `donts[5]` said to "say 'livrés régulièrement'", and
`voice_style` restated the language rule with the same escape hatch the global
rule had. A brand-specific instruction beats a global one, so no amount of
prompt tightening could have fixed it. All three are now English, plus
FancyFinds' "apéro".

`ENGLISH_ONLY_RULE` lost its escape hatch and now names both what qualifies
(company, supplier, product, certification, place) and what does not, by
example. `shared/language_guard.py` (new) detects French deterministically —
markers with no English homograph, plus accented spellings outside a loanword
allowlist, with proper nouns masked first. Planning gained a fourth
post-generation pass that reports but never rewrites; the video graph checks the
shot plan **before** the render and re-asks once, because a wrong-language plan
costs one text call while the render it precedes costs tens of GPU-minutes.

**Measurement correction worth recording.** The first sweep counted 32 French
content rows and 9 French reels, and ~5.5 GPU-hours of re-render were queued on
that basis. `content` is **versioned** — `store_content` flips prior rows to
`is_current = false` — so 21 of those were superseded versions nobody sees.
Filtering on `is_current` gives **4** genuinely affected items. The batch was
stopped after one reel. Any future content-quality sweep must filter on
`is_current` or it will measure history.

**Image text guard: two independent failures found by the gate study.** The
request pinned `"temperature": 0`, which the default vision model rejects (HTTP
400); it worked only because litellm's `drop_params` strips it, so any
direct-to-provider guard model silently failed open on **every image** while
reporting itself enabled. Separately, the prompt asked only about lettering "you
can read" and excused unresolvable blur — so all five of one candidate's
invented-text failures were recorded as "none resolvable" and passed. The schema
gained `illegible_text_marks`. Note that 40 stubbed unit tests passed throughout
against a detector that missed the defect it exists to catch.

**Local image models.** Bake-off complete on the hex-free suite;
`docs/LOCAL_IMAGE_MODELS.md` carries the verdicts and licence audit.
`LOCAL_IMAGES=1` routes stills through the Video Forge (Z-Image base,
Apache-2.0), off by default with the cloud cascade intact. Honest ceiling: no
candidate yet clears `ai_artefact_absence >= 3 on every prompt`, so this is a
cost lever to evaluate, not a replacement.

**Still blocked on the user:** BC API admin grant (app
`47d43367-a8d9-4d61-9c9a-1678a508ebc7`, tenant
`33b8e89b-0b2f-42b1-b59c-835bd0c2ce3c`) — `API.ReadWrite.All` + admin consent,
then the app registered inside BC `Production` with D365 BASIC + D365 READ.
Healthspan product photos are deliberately **not** web-sourced pending it.

**Cycle-7 backlog:** unchanged from cycle 6 — product-swap lettering contract,
logo/headline collision on 1536×1024, `visual_direction` validated against
`item_type` at planning time, n8n workflow import, observability, token
encryption, Qdrant learning loop.

## Cycle 7 — Reel finishing: what nobody had measured (2026-08-19)

The brief was "the videos are not great — QA them properly". Everything below
came from measuring delivered reels or looking at their frames, not from
reading code. Where a number appears, it was measured.

**Loudness: the largest single defect, and nothing had ever measured it.**
Against the −14 LUFS platform target, four delivered reels came in at −19.9,
−34.8, −42.6 and −43.0 LUFS with 17–27 LU of internal range. At −43 LUFS a
viewer scrolling a feed at normal volume hears nothing at all, and a 23 LU
spread *between* reels means the same brand is inaudible in one post and
merely quiet in the next. `video_jobs` recorded `"audio": true`
unconditionally throughout, so nothing downstream could tell.

ffmpeg's `loudnorm` was the obvious tool and does not work on this material:
its two-pass form landed at −11.5/−21.7/−18.2/−20.4 LUFS and clipped twice.
Its dynamic mode rides gain frame by frame, so an input range far above the
target lifts gated-out quiet passages into the measurement and drifts; and
its warmup eats most of the correction on a 5 s clip. Replaced with a
measured flat gain, converged over up to four **decode-only** rounds, into an
oversampled true-peak limiter. `alimiter` alone caps the *sample* peak and
delivered up to +1.2 dBTP; 4× oversampling plus a ceiling 2 dB under target
absorbs the resample and AAC overshoot. All four reels now deliver
**−14.3 … −14.5 LUFS at −2.3 … −0.6 dBTP**, none clipping. Verified again on
a live render: −29.7 → −14.2 LUFS, +15.7 dB in 2 rounds, peak −3.0 dBTP.

A music bed is laid under that when one exists — supplied as files by the
operator, never generated and never fetched, because the licensing call is
theirs. With no bed the pass still normalizes and says so.

**Chain drift.** Every shot was i2v from the previous shot's last frame, so
shot 8 sat seven generations from the branded keyframe; across one reel the
pack name degraded `KAOKA → KOOKA → ҠӒOKA`. Depth is now capped at 2. The
first version of the cap was gated on `keyframe` and therefore never fired on
reels that *have* no keyframe — the case where drift is worst — which a live
render exposed immediately (shot 6 "from chain+5"). A reel now **adopts** an
anchor: the keyframe when there is one, shot 1's last frame otherwise. The
anchor label was lying too, reporting "keyframe" for text-to-video shots,
which is why the missing cap was invisible.

**Dead shots.** i2v fails by returning its input image held for five seconds
— a clip that passes every structural check the pipeline had. Shots are now
measured (mean inter-frame luma difference) and a frozen one buys one
re-render from the anchor, kept only if it measures better. Calibrated
against footage rather than guessed: held-still control **0.001**, slowest
real beat **0.53** (a hand breaking chocolate), ordinary beats **1.2–5.3**,
fast dolly **9.29**. The floor is **0.25**, deliberately biased toward
letting a slow shot through. The first guess of 1.0 would have re-rendered a
perfectly good beat.

**Burned type.** Lines were centred at (540,1130): on 1080×1920 that runs a
long line to x=1015 — under the action rail — and lands the block where a 9:16
product shot puts the bottle and the presenter. Rendered frames showed lines
sitting on an olive-oil label and across a presenter's chest. Now bottom-left
on a measured safe box, on a feathered translucent scrim (white over a pale
wall was barely readable), with the CTA colour contrast-checked and demoted to
white below 3:1 — Naturespan's lime measured 2.14:1 and had shipped as bright
green letters over a warm brown dinner scene. `_clean_overlay_text` now
*simulates* the wrap instead of counting characters, which stops it dropping
the last word of 26–33% of lines.

**Copy.** A reel held "AB Ecocert Eurofeuille," on screen for a full beat: a
trailing comma promising a continuation the next cut never delivers, and a
certification body transcribed off the pack instead of a claim. Lines are now
closed deterministically after the wrap budget, and the prompt says outright
that regulatory wording is packaging copy, not on-screen copy.

**Pacing.** The JSON example anchored `"duration_s": 4.0` and the model copied
it onto every beat — a reel that ticks like a metronome.

**A branded close.** Reels ended on whatever frame the last i2v landed on. A
2.4 s end card now carries the mark and the CTA; on a reel of generated
footage it is the only frame guaranteed to be on-brand. Three defects were
found by rendering it and looking: libass's `BorderStyle 3` boxes each *line*,
so a two-line CTA came out as a ragged step (replaced with one drawn chip);
the chip width estimate of 0.56 em drew a button nearly twice its label
(measured: 0.325); and a decorative rule landed a second green line under a
wordmark that already carries one.

**Invented pack lettering.** A reel carried "FIIRE CMIS", "THETE CCRE MAITENE
OL" and "TWTL CCRE PAILSNEWE" across seven shots. The swap had correctly
refused — the product's only image is a 1200×630 share banner whose actual
pack trims below the swappable floor — so nothing anchored the pack and the
model drew a label from nothing. The existing rule ("never make the label the
subject") was *obeyed* and did not help. When no keyframe survives, every shot
prompt now forbids readable printed copy outright and states what correct
output looks like.

**One swap, not two.** `worker.py`'s regeneration path carried its own copy
that returned the editor's first output **unread** — no fabrication guard, no
retry, no vendor in the allow-list. That is the button a reviewer presses
*because* the image was wrong. Both callers now use
`shared.product_swap.swap_product_into_image`.

**A message that could never succeed, retried forever.** Requeueing a reel
with `trigger='manual-qa'` violated `agent_runs_trigger_check`; the worker
logged it as "already running" and NAK'd every 5 minutes indefinitely while
the reel sat in `queued` and the logs blamed a run that did not exist. Only
the idempotency index means "already running" now.

**Still blocked on the user:** BC API admin grant (unchanged from cycle 6).
This cycle showed its cost concretely — the Emile Noel reel had no usable
product photo, which is the upstream cause of both the missing keyframe and
the invented lettering.

**Cycle-8 backlog:** music beds once licensing is decided — with none, a reel
whose diegetic track measures −54.8 LUFS hits the +40 dB makeup clamp and
lands at −20.2, correctly reported `OFF TARGET` rather than shipping 40 dB of
amplified hiss; a picture grade *if* measurement supports one (the sample so
far is mixed — some frames are muddy, others are well-exposed pour shots a
global grade would damage, so this needs the per-reel measure-then-correct
treatment the audio got, not a blanket curve); logo/headline collision on
1536×1024; `visual_direction` validated against `item_type` at planning time;
n8n workflow import; observability; token encryption; Qdrant learning loop.

## Cycle 8 — The picture, measured against our own stills (2026-08-19)

Cycle 7's backlog said a picture grade needed measurement, not a blanket
curve. This cycle took the measurement, and it settled the question.

**The gold standard was already in the app.** The operator named the
gpt-image-2 stills as the quality bar, so the target came from them rather
than from a number someone picked. Thirty stills sampled from
`content-images`, medians:

| | YLOW | YAVG | YHIGH | SATAVG |
|---|---|---|---|---|
| gpt-image-2 stills (n=30) | 60 | 140 | 214 | 19.2 |
| delivered reel, per second | 26 | 91 | 194 | 10.4 |

The footage is **~35% darker** than the stills and carries **roughly half**
their colour. Neither is a taste call: nothing in the reel clips — YHIGH
never reaches even 235 — so the headroom was simply unused. YHIGH also
**decays from 207 to 139** across the reel as the i2v chain washes contrast
out, which is why the correction is per shot. One curve for the whole master
would over-lift the opening and still leave the ending flat.

**Gamma alone was not enough, and the first pass proved it on screen.**
Lifting YAVG 92.8 → 132.8 also dragged YLOW 31.5 → 72.6 against the stills'
60. Thirteen points of raised black is what "washed out" looks like, and it
was visible on the contact sheet — the numbers had improved and the picture
had not. Gamma has one control and there are two targets. Subtracting a black
point first (`colorlevels`, all three channels together so shadows stay
neutral) supplies the second, and the gamma is then solved for what that
leaves. Measured on the real master:

| | YLOW | YAVG | YHIGH | SATAVG |
|---|---|---|---|---|
| before | 31.5 | 92.8 | 186.5 | 11.1 |
| after | **63.3** | **128.5** | **211.5** | **19.4** |
| stills | 60 | 140 | 214 | 19.2 |

Three of four land. YAVG stops 11 short because two shots hit the gamma cap
of 1.95 — the flattest ones — and pushing past that to chase the last 8% of
mean would spend the tonal separation the black point just bought. Clipping
went *down*: 433 frames at ≥254 against 739 in the source (white captions and
real speculars, both already there).

The chain rides along in the overlay burn's encode, so the reel pays for no
extra pass, and runs before the subtitle filter so captions keep the contrast
they were designed with. The `enable` expression is **escaped, not quoted** —
verified in the deployed container: the form the ffmpeg docs show is a *shell*
command line, and passed as one argv element its quotes reach the expression
evaluator and break it.

**The delabel pass was fixing a beat that should never have been planned.**
It rewrote all seven scenes of a reel and the render still came back reading
"SCNE CONFEXT" and "CIABE INN TEHMTS" on a hero bottle. The stored plan says
why: the REVEAL beat asked for "the bottle revealed whole at natural distance
… LOCKS: bottle whole and visible", and a rewrite appended after a scene
loses to the scene. Swappability is one HTTP fetch, so it is now settled
between `source_product_image` and `plan_shots` and the planner is told not
to write a hero-pack beat it cannot back. The check landed a node too early
on the first attempt — in `load_context` there is no `product_image` yet, so
it read "no pack" on *every* reel; the live log caught it by the absence of
the line it should have printed. The graph test now asserts the wiring, not
just the function.

**A discarded keyframe was a wasted generation and a lost anchor.**
`make_keyframe` asked "did the swap work?" only after paying for the answer:
it generated a 1024×1792 frame built around a blank placeholder, ran the swap,
watched it refuse on a 1200×630 share banner, and threw the frame away — one
image call and ~2 minutes to learn what one fetch answers, leaving shot 1 to
render t2v. It now asks first and, when the answer is no, composes a frame
with deliberately unreadable packaging and **keeps** it. That split two facts
`render_video` had fused, so `unverified_pack` reads a state flag instead of
the keyframe bytes — reading the bytes would have switched the directive off
for exactly the reels that need it.

**Measured but not shipped: subject presence.** Several beats are 4–5 seconds
of an out-of-focus bowl. They pass the motion check (they move) and the tone
check (they are exposed). Edge energy does separate them — 3.32 for the empty
bowl against 4.4–5.9 for real shots — but 1.3× on a single reel is not a
calibration. The motion floor was calibrated against four reels before it
shipped; this gets the same treatment or none.

**Still blocked on the user:** BC API admin grant (unchanged from cycles 6–7).

**Cycle-9 backlog:** subject-presence detection once there are enough reels to
calibrate against; music beds once licensing is decided; logo/headline
collision on 1536×1024; `visual_direction` validated against `item_type` at
planning time; n8n workflow import; observability; token encryption; Qdrant
learning loop.
