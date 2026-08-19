# Image QA — Healthspan.mu (`healthspan`)

Brand id: `1f83f59b-6d04-41fd-91d2-09b5fcaaebd7`
Scope: every `in_review` calendar item of `item_type = 'post'` — **13 items**
Asset audited per item: `content.generation_metadata->>'generated_image_url'` → `content-images/<brand>/<item>/branded.png`
Method: bytes pulled from MinIO, each frame sent as a base64 data URL to LiteLLM `gpt-5.4` (`json_object`, `temperature 0`) with one multi-axis QA prompt; **every verdict then re-checked by eye**, with pixel crops of each disputed region.
Date: 2026-08-19

---

## Headline numbers

| | Count |
|---|---|
| Items audited | 13 |
| Clean — publishable as-is | **6** |
| Blocker present | 4 |
| Major (no blocker) | 3 |
| Distinct defects logged | 15 |

**Axes that came back clean across all 13:** every frame has a real subject (no empty set-dressing — none of the Naturespan "blank wall" failure mode), no anatomy or limb artefacts, and no off-palette frames. The cyan/blue art direction is consistently on-brand.

**Where the failures are concentrated:** the compositing step, not the image generation. Nine of the fifteen defects are the overlay pipeline colliding with itself, duplicating itself, or stamping a badly-prepared asset. The photography underneath is largely good.

---

## Root causes (verified, not inferred)

### 1. The brand logo is stamped twice — because the category logo *is* the brand logo

`da245678` and `b5d4cf49` each carry **two Healthspan lockups**, in opposite bottom corners, at different sizes and in different colour variants.

I ruled out generation: I pulled `background.png` and `composed.png` for both items and **neither contains any logo**. Both lockups are added at the `branded.png` step.

The mechanism is `apply_branding` in `agents/workflows/content/nodes.py` (~line 2786), which passes a *second* logo into the same overlay call:

```python
pl_kwargs = {
    "product_logo_data": pl_bytes,
    "product_logo_dark_data": pl_dark_bytes,
    "product_logo_xy": tuple(_pl_xy) if _pl_xy else None,
    "product_logo_scale": state.get("product_logo_scale"),
}
```

That product logo resolves from `brand_guidelines.category_logos[category]` (~line 1536). For Healthspan, the `SUP-TOOLS` entry — the category covering the blood pressure monitors and thermometers — was populated with **the Healthspan logo itself**:

- `category-logos/sup-tools-light.png` is pixel-identical artwork to `logos/primary.png` (cyan gradient lockup)
- `category-logos/sup-tools-dark.png` is pixel-identical artwork to `logos/light.png` (black lockup)

So every SUP-TOOLS post gets the brand logo in one corner and the same brand logo again in another. Fix at either level: clear the `SUP-TOOLS` entry from `category_logos` (own-brand products have no separate vendor mark), or guard in the resolver so a product logo matching the brand logo is skipped.

### 2. The headline banner and the logo are placed independently, so they collide

Three items have the two overlays occupying the same pixels. `find_best_logo_position` picks a clean region without knowing where the headline block will land, and the headline spans full width into that same region.

- `fc451c32` — worst case: the headline bar runs straight through the logo mark, "check in" is overprinted on the black mark, spokes protrude above and below the bar.
- `849dfd79` — the cyan mark is drawn *on top of* the bar, obscuring "Start with". (Note the z-order is inverted vs `fc451c32` — the two overlays have no defined stacking contract.)
- `4c54ccf8` — milder: the mark's top spoke intrudes into the bar and reads as a stray black blob between "feel" and "urgent".

All three are landscape 1536×1024 LinkedIn/Facebook frames, where the full-width headline bar reaches the top-right corner the logo placer favours.

### 3. Two product-logo assets have a baked-in opaque black background

`category-logos/reus-wear-dark.png` (RingConn) and `category-logos/disp-wear-dark.png` (SIBIONICS) are stored as white artwork on a **solid black rectangle**, not on transparency. When the pipeline selects the dark variant it stamps the rectangle too.

That is the black plaque in the bottom-left of `c038f7fb`. The light variants of both are correctly transparent — only the dark ones are broken. Re-cut both assets with a real alpha channel.

### 4. Generated device screens and packaging carry invented lettering

Consistent across every frame containing a device with a display. Severity scales with how large the text is: trivial on a 40px thermometer LCD, a blocker on `c4a528a2` where the box and phone dominate the frame.

Also worth flagging to the client: on `da245678` and `c24c92e3` the generator printed **"Healthspan" onto the blood pressure monitor itself**. Healthspan is a retailer, not the manufacturer — that is an implied own-brand claim in the artwork.

### 5. Data note — `product_ids` are dangling

`select count(*) from products where brand_id = '1f83f59b-…'` returns **0**. Every `product_ids` reference on these 13 calendar items points at a row that no longer exists. This is why captions carry raw BC catalogue strings in caps ("BLOOD PRESSURE MONITOR", "DIGITAL THERMOMETER") instead of resolved product names, and why item `4422a4b3` says "DIGITAL THERMOMETER" in the brief but "INFRARED THERMOMETER" in the caption. Copy-side issue, outside this image audit, but it will keep producing awkward captions until the catalogue is re-synced.

---

## Item-by-item

### Clean — publishable as-is (6)

#### `57fc29d7-f0d8-410d-b65c-92c2b506eed1` — "Trends matter more than perfect days" (instagram, 1024×1024)
**CLEAN — best in set.** Silver smart ring with its charging case on a warm wood table; teal towel and teal bottle carry the brand palette without shouting. Black logo top-right on a soft blurred blue-green backdrop, generous margins, nothing near it. Headline in white on a dark grey pill top-left, high contrast, no scene detail behind it. Caption names the Silver variant and the ring in frame is silver — correct. No stray text anywhere.

#### `4422a4b3-9ea0-4ea5-83cb-f040106add0d` — "A quick check can guide next steps" (facebook, 1536×1024)
**CLEAN.** The strongest *marketing* frame of the set: a real human moment, a woman taking a boy's temperature with a non-contact IR thermometer, exactly on brief. Black logo top-right on pale blue wall, verified by crop to be fully inside the frame with a real margin. Headline dark-on-light-grey pill top-left, legible. Hands and faces are anatomically clean.
*Minor:* the thermometer LCD shows scrambled amber digits — roughly 40px, invisible at feed size.

#### `3530fb82-9bb1-4e0e-ad84-d8758b26ec91` — "5 minutes to check in better" (instagram, 1024×1024)
**CLEAN.** Hand holding a black smart ring over a wooden table, blurred palms and sea behind. Pinch grip reads correctly — fingers and thumb are properly formed. Black logo top-right on clean sky, well clear of the headline pill. Warm wood dominates but the cyan mug and blue sea keep it on-brand. No stray text.

#### `f47957d7-5396-4766-965a-5ea8deac6b04` — "5 daily signs your body sends" (facebook, 1536×1024)
**CLEAN.** Gold ring on a stone podium, premium product-still treatment. Headline white with a cyan "5" and a firm drop shadow on a pale blue gradient — strong. Healthspan cyan lockup bottom-left reads clearly against the mid-grey floor. RingConn wordmark bottom-right is the *light* product-logo variant, correctly transparent and correctly spelled.

#### `a19dc84a-b604-4b34-bb82-8338b2434e75` — "Mid-year check-in starts with your body" (instagram, 1024×1024)
**CLEAN.** Gold ring hero, pale cyan wall, palm frond and pebbles as restrained set dressing. Headline is white on light cyan — I zoomed this one specifically because it looked marginal, and the drop shadow carries it; it reads cleanly. Healthspan cyan lockup bottom-left, RingConn light variant bottom-right, both legible and both intentional.

#### `c24c92e3-2b3a-4a32-a370-c51a35f128ce` — "Build a clearer blood pressure baseline" (linkedin, 1536×1024)
**Publishable, two minor notes.** A man at a table with the cuff on his arm, monitor on the tabletop — a genuine, on-brief use scene. Black logo top-right on a plain beige wall, excellent contrast and separation. Headline dark-on-light pill top-left, legible.
*Minor:* fabricated Healthspan-style branding printed on the monitor, plus garbled micro-labels around the "108 / 60" readout.
*Minor:* the top of the man's hair is cut by the frame edge. The vision model called this a blocker — **I disagree**; it is a normal tight editorial crop and no marketing director would reject it.

### Major defects (3)

#### `4c54ccf8-1395-4933-9e76-06362081400c` — "Track health trends before they feel urgent" (linkedin, 1536×1024)
**MAJOR — logo/headline collision.** Verified by 2× crop: the top spoke of the logo mark pushes up into the headline pill and lands as a stray black blob between "feel" and "urgent".
Everything else is good — a woman writing in a notebook, gold ring on the table at lower right matching the caption, clean pale wall behind the logo, strong white-on-dark headline.
The vision model passed the placement and instead flagged the top-of-head crop as the blocker. **Both calls were wrong**: the collision is the real defect, the hair crop is normal.

#### `849dfd79-041d-4d8f-9dd1-983f44e921ad` — "Start with a 2-minute body check" (facebook, 1536×1024)
**MAJOR — logo overlaps headline.** The cyan mark is composited on top of the headline bar, cutting through "Start with". Placement is doubly wrong: the entire lower-right wooden table is clean open space, and the placer chose the one corner already occupied by the headline.
*Minor:* three rings are visible in two finishes — the black hero on the table, a gold band on the model's finger, a gold ring in a dish at bottom-left — while the caption names the Black. Reads as product confusion.
Otherwise strong: real subject, beach setting, on-brand teal, clean anatomy.

#### `c038f7fb-7506-4b02-9d7e-bb80be001fa0` — "What is your body repeating?" (instagram, 1024×1024)
**MAJOR — black plaque artefact.** An opaque black rectangle sits at bottom-left with tiny near-illegible "RingConn" lettering inside it: the `reus-wear-dark.png` asset stamped complete with its baked-in black background (see root cause 3).
The rest is clean — gold ring on a stone podium, black logo bottom-right legible over pale water, white/cyan headline strong against the pale gradient.

### Blockers (4)

#### `fc451c32-d9b5-4852-8e22-1fd9a6942bb3` — "Mid-year is a good time to check in" (facebook, 1536×1024)
**BLOCKER — headline bar driven straight through the logo.** The most severe collision in the set: "check in" is overprinted on the black logo mark and the mark's spokes protrude above and below the grey bar. Confirmed at 2× crop. Neither element survives intact — the logo looks damaged and the last two words are hard to read.
*Minor:* the blood pressure monitor is cut off by the bottom frame edge.
The underlying photograph is genuinely good — an older woman with the cuff on, sea behind, teal palette bang on brand. Re-render the overlay and this becomes one of the better items.

#### `da245678-0fb2-42e9-85c2-2853f844935d` — "Checking your baseline starts at home" (instagram, 1024×1024)
**BLOCKER — two Healthspan logos**, bottom-left (large, cyan gradient) and bottom-right (smaller, cyan). Absent from both `background.png` and `composed.png`; added at the branding step. Reads unambiguously as a compositing error.
**MAJOR — hallucinated device text.** The LCD reads **"OYS"** where it should read SYS and **"DA"** where it should read DIA, with a garbled "12·08" clock. A health brand publishing a blood pressure monitor with misspelled medical labels is a credibility problem, not a cosmetic one. The monitor also carries a fabricated "Healthspan" wordmark on its face.
Headline and composition are otherwise fine.

#### `b5d4cf49-52c4-4209-9b0b-c314e035d557` — "Busy weeks can raise blood pressure quietly" (facebook, 1536×1024)
**BLOCKER — two Healthspan logos**, and here in *different variants*: cyan gradient bottom-left, solid black bottom-right, at different sizes. Visibly inconsistent even to a casual viewer.
**MAJOR — headline buries the hero.** "pressure quietly" is laid directly across the monitor's LCD; the product is unreadable behind the type.
**MAJOR — garbled lettering.** The buttons read "S7A8T" and "MEMOQY" (for START / MEMORY) and the screen digits are illegible.
Subject and palette are fine; the overlay work is not.

#### `c4a528a2-e022-40cc-9ab9-90cbd4116011` — "Better body visibility supports steadier workdays" (linkedin, 1536×1024)
**BLOCKER — worst image in the set. Do not publish.**
- **Headline illegible.** Five lines of oversized white type dumped across the whole product hero. Verified by 1.6× crop: "supports" and "steadier" are white-on-white over the SIBIONICS box and the white applicator, held together only by a thin grey outline. They lose their edges entirely.
- **Headline buries the hero.** The box, the applicator and the phone — the entire reason for the post — are behind the type.
- **Hallucinated text throughout.** "SƆINOIBIS" mirrored upside-down on the top face of the box; paragraphs of gibberish micro-copy on the front panel; a fabricated phone UI with nonsense sentences ("A lenoi ollande englii ac…"); an invented "8.6" glucose reading presented as real data.
- A floating "SIBIONICS" wordmark sits over empty tabletop at bottom-left.

Needs regeneration, not a re-render — the underlying frame is unusable.

---

## Recommended fix order

1. **Clear `category_logos['SUP-TOOLS']`** from Healthspan's `brand_guidelines` (it duplicates the brand logo). Add a resolver guard so a product logo identical to the brand logo is never stamped. — kills 2 blockers.
2. **Make the headline block and the logo placer aware of each other.** Reserve the headline's bounding box before `find_best_logo_position` runs, and fix the stacking order. — kills 1 blocker + 2 majors.
3. **Re-cut `reus-wear-dark.png` and `disp-wear-dark.png`** with real alpha. — kills 1 major.
4. **Constrain headline size/placement against the product mask** so type never lands on the hero. — kills 1 blocker, improves 1 more.
5. **Suppress generated lettering on device screens and packaging** at the prompt level, and explicitly forbid printing "Healthspan" onto third-party hardware.
6. Re-sync the product catalogue — `products` is empty for this brand.

Items 1–4 are re-renders from the existing `composed.png`, so 3 of the 4 blocked items can be recovered without paying for regeneration. Only `c4a528a2` needs a fresh image.
