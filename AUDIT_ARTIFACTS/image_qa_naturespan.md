# Image QA audit — Naturespan, all `in_review` posts

**Brand:** Naturespan (`8d0fb129-4797-4003-8457-edbd20f9dfcd`)
**Scope:** every `calendar_items` row with `status='in_review'` and `item_type='post'` — 16 items
**Asset audited:** `content.generation_metadata->>'generated_image_url'` → `branded.png` (the composited image the app displays)
**Method:** bytes pulled from MinIO inside `markai-agents`, each posted as a base64 data URL to LiteLLM `gpt-5.4`
(`response_format: json_object`, `temperature: 0`, same call shape as `backend/app/api/v1/products.py::_image_depicts_product`),
then every verdict re-checked by hand against the pixels, with contrast measured numerically.
**Date:** 2026-08-19. Read-only — no production row was modified.

---

## Headline result

| | count |
|---|---|
| Items audited | 16 |
| **Fully clean — publish as-is** | **4** |
| Publishable with a noted nit | 2 |
| Send back (blocker or major) | 10 |
| Distinct defects logged | 20 |

Four images are genuinely excellent and should be signed off untouched:
**"7 days to shop certified organic"**, **"Real brands, real proof on pack"**,
**"Start at our food truck, shop tomorrow"**, **"Tomorrow, certified organic begins here"**.

---

## The two root causes

### 1. Logo contrast — the brand has only ONE logo variant, and the review step is skipped for ad posts

Two independent faults compound:

**(a) There is no light logo to select.** `brands.brand_guidelines->'logos'` for Naturespan contains
**`primary` only** — no `dark`, no `light`, no `watermark`. So
`agents/shared/image_processing.py::select_logo_variant` (line 279), whose whole job is to return the
light variant when `brightness < 100`, has nothing to return. Every one of the 16 items records
`logo_variant_used: "primary"` — the dark-green wordmark — including the ones placed on dark surfaces.

**(b) The contrast check never runs on these posts.** `agents/workflows/content/nodes.py:3120-3122`:

```python
if state.get("image_format", "lifestyle") == "ad":
    logger.info("review_branding: skipped for ad/headline post")
    return {"branding_review": {"ok": True, "reason": "ad headline (AI-placed)"}}
```

8 of the 16 items carry exactly that `branding_review` value. Those 8 are precisely the ones whose
`logo_xy` sits at the **bottom** (y = 0.86–0.90) — a position
`find_best_logo_position` can never produce, because it only offers `top-right` and `top-left`
(image_processing.py:162-165). So on ad posts the logo position comes from the art-director LLM,
bypasses `analyze_logo_region_brightness` entirely, and then bypasses the review that would have
caught it. The other 8 items are top-corner placements on sky, and every one of those got a real
review verdict with a substantive reason.

The correlation with measured contrast is exact. Background contrast against the dark wordmark ink,
sampled under the wordmark (WCAG large-text floor is 3.0:1):

| Item | logo_xy | placement | measured contrast under wordmark |
|---|---|---|---|
| Real brands, real organic proof | [0.14, 0.88] | AI, bottom | **1.74 – 3.27** (mean 2.15) ❌ |
| Start online, visit us from September 1 | [0.84, 0.90] | AI, bottom | **2.69** ❌ (pale wall above measured **6.77**) |
| One week to shop with ease | [0.86, 0.90] | AI, bottom | **1.82 – 7.72** ❌ (dappled — see below) |
| 7 days to certified organic clarity | [0.82, 0.86] | AI, bottom | 4.52 ✅ |
| Two new organic doors | [0.86, 0.90] | AI, bottom | 5.66 ✅ |
| 7 days to shop certified organic | [0.79, 0.24] | scanned, top | 7.54 ✅ |

**"One week to shop with ease" is the clearest case and confirms the hand-observed defect.** The logo
was placed on the shadow-dappled wood plank along the bottom. Background luminance *under the
wordmark itself* swings from contrast **1.82 to 7.72** — the left half of "Naturespan" sits at ~1.8:1
and effectively vanishes, while the leaf mark lands on a lit patch and reads fine. That band is the
**least uniform region in the frame** (contrast spread 5.91); the large open pale-green wall
occupying the middle-right was measurably calmer (spread 3.43) and was not used. So the placement
chose a bad region *and* the variant logic had no light logo to fall back on. The logo is **not**
clipped — margins are correct throughout the set (I re-measured; the two cases I initially suspected,
"Countdown to certified organic aisles" and "First look at our organic shelves", both have real
margin: ~50px and ~31px on a 1536px canvas. No clipping defect exists in this batch.)

**Fix points:** upload a light/reversed Naturespan logo so `select_logo_variant` has something to
pick; and either remove the `image_format == "ad"` early return in `review_branding` or replace it
with a contrast-only check that re-renders the logo (not the headline) when the region falls below
3:1.

### 2. Empty frames — the predictor is whether a product is linked, not the brief wording

**All 6 items with a populated `product_ids` produced a strong subject-led frame — 6 of 6.**
**All 5 weak/empty frames are among the 10 items with no linked product.**

| linked product | items | empty frames |
|---|---|---|
| yes | 6 | **0** |
| no | 10 | **5** |

When a product is linked, the prompt gets a concrete nameable hero — a jam jar, an arnica bottle, a
clay tube, a pistachio jar — and the model renders it every time. When `product_ids` is empty, the
prompt falls back to the `visual_direction` string, and for these announcement/countdown items that
string describes either a *video* or an abstract *space*, never a hero object:

- "One week to shop with ease" → *"Fast but polished montage of shelf details, signage mockups, food truck footage and a closing countdown card reading J-7."*
- "7 days to certified organic clarity" → *"Bright, premium reel with exterior tease, shelf close-ups…"*
- "Start online, visit us from September 1" → *"Fast, polished sequence moving from food truck to online shop interface…"*
- "Proof first, before we open" → *"Clean editorial-style graphic or shelf image featuring certification marks…"*

A still-image model cannot render a montage, a sequence, or "signage mockups", so it renders the only
thing left — set dressing. Result: a green wall and a plank, a green wall and a marble slab, a green
wall and a fence, a bare wall and a light shaft. Note that 8 of the 16 `visual_direction` values are
video-shaped even though every one of these rows is `item_type='post'` — the still-post briefs are
being written as if they were reels.

The counter-examples prove this is fixable at the prompt level, not a model limitation: six items with
no linked product still produced excellent frames — the food truck, the seaside family, the storefront,
the grower — because their briefs named **people, a truck, a storefront**. The failure is not "no
product" per se, it is "no nameable hero of any kind".

**Fix point:** when `product_ids` is empty, the image-prompt builder must not pass a video-shaped or
space-shaped `visual_direction` through. It should be required to resolve to one concrete hero subject
(a person shopping, a storefront exterior, a shelf with real packs) before generation, and
`visual_direction` for `item_type='post'` should be validated as still-image language at planning time.

A related, separate failure of the same kind: **"Two new organic doors, clearly certified"** rendered
the copy's *metaphor* literally — two actual garden doors in an empty room, when "two new doors" meant
two new stores.

---

## Item-by-item

Legend: ✅ clean · ⚠️ ships with a nit · ❌ send back

### ✅ CLEAN — publish as-is

**`9940c6a5-1e5e-4717-822c-82cd0fd2f1aa` — "Real brands, real proof on pack"** (instagram, 1024×1024)
Amber Pranaróm Arnica bottle on a stone plinth, soft green background. Label reads
"PRANARŌM / Huile végétale / 100% pure et naturelle / ARNICA / Arnica montana / - Fleurs - / 50 ml" —
real, coherent, correctly spelled, and an exact match for the captioned *Pranarom, Arnica, 50ml*.
Logo bottom-left, wordmark readable. Headline upper-right, all words read. No artefacts. Palette
dead-on. **This is gold-standard work.**

**`81ccce46-8abc-45dd-868c-1d2034f088da` — "Start at our food truck, shop tomorrow"** (facebook, 1536×1024)
A vendor leaning from a green food-truck window serving a girl and an older man. Real human
interaction, strong focal subject. Logo top-right on clean pale sky — crisp. Headline top-left in a
light pill, fully legible. No invented lettering anywhere in the scene. No anatomy problems. Clean.

**`a8da2d49-47dc-45d0-b9ff-fff10b1ce094` — "7 days to shop certified organic"** (facebook, 1536×1024)
A Mauritian family — mother, father, toddler — palms and lagoon behind. Logo top-right on open sky,
measured **7.54:1** contrast, the best in the set. Headline top-left in a dark pill. I checked the
child's legs and the mother's hand at full resolution after the model flagged them; they are fine.
Clean.

**`e25991c0-56e8-40ed-8393-c9bfdddadd2b` — "Tomorrow, certified organic begins here"** (facebook, 1536×1024)
Warm dusk storefront with a family arriving, café terrace running right, stocked shelves visible
inside. Logo top-right on bright sky, crisp. Headline top-left in a light pill. Credible, premium,
on-message for an opening announcement. Clean.

### ⚠️ SHIPS, WITH A NIT

**`1c5a938b-0b2e-4e7c-9e9c-b447fb5c5a18` — "First look at our organic shelves"** (facebook, 1536×1024)
Excellent product shot. Jean Hervé "PURÉE PISTACHE / PRODUITS BIO & SOLIDAIRES / 100 g / FABRIQUE EN
FRANCE" — real, correctly spelled, and an exact match for the captioned *Jean Herve, Pistachio Puree
Origin Spain, 100g*. Logo bottom-right, fully readable, ~31px margin (tight but not clipped).
*Nit:* the headline promises "shelves" and the frame shows a single jar on a rock — no shelf anywhere.
Minor copy-to-image mismatch.

**`b1e17c61-1c49-44c5-b93d-1bf6a62470cf` — "Grand Baie, your organic table awaits"** (instagram, 1024×1024)
Family of three on a rattan sofa, tropical greenery, soft evening light. Logo top-right on sky, crisp.
Headline in a dark pill at the bottom, legible.
*Nit:* the line is about the Grand Baie 100% organic café-restaurant — "your organic table awaits" —
and there is no table, no food, no café in the frame. Minor concept mismatch.

### ❌ SEND BACK

**`0c3d71d9-90a5-4883-844c-941209199573` — "One week to shop with ease"** (instagram, 1024×1024) — **BLOCKER**
- **empty_frame (blocker):** a pale green wall, a wooden plank, and a leafy branch. No product, no
  person, no storefront, nothing to look at. "One week to shop with ease" over an empty wall is not a
  marketing asset.
- **logo_illegible (major):** dark-ink wordmark on the shadow-dappled wood band; background contrast
  under the wordmark swings **1.82–7.72**, so the left of "Naturespan" sits far below the 3:1 floor and
  nearly disappears while the leaf mark reads.
- **logo_misplaced (major):** `logo_xy [0.86, 0.90]` put it on the least uniform region in the frame
  (spread 5.91); the large open pale wall in the middle-right was calmer (spread 3.43) and unused.
- Not clipped — margins are correct.

**`88d92f88-14c3-4113-91e9-fd8979d23abe` — "Countdown to certified organic aisles"** (facebook, 1536×1024) — **BLOCKER**
- **hallucinated_text (blocker):** the Favrichon Granosson pack body copy is gibberish. Verbatim from
  the pixels: *"Une recette croortillante an blé fomgnis pour nn. bien-être dlgestil inedit"*,
  *"IVOVT on FIBBES / se 6ON ot BLE"*, *"SOURCE ce PROTEINES"*,
  *"RICHE au FER, MACROUOM ut PHOESNORE"*, *"FABRIQUÉ A / ST SYMPHONIEN SI LAY"*. Favrichon is a real
  supplier the brand names by name; publishing a fake, misspelled version of their pack is a
  legal-and-credibility problem for a brand whose entire pitch is "read the label and verify".
- **wrong_product (major):** the front pack reads **290g**; the caption and the linked product both
  say **250g**.
- **anatomy_artefact (major):** three cloned copies of the same pouch, the rear two with warped,
  melted-looking side seams — and the three copies show *different* weights (210g / 290g / 290g).
- Logo and headline themselves are fine and not clipped.

**`3d18f709-f2d3-4311-a8f8-226a6509fba8` — "Start online, visit us from September 1"** (instagram, 1024×1024) — **BLOCKER**
- **empty_frame (blocker):** a green wall, a green marble slab, and a plant. No food truck, no online
  shop, no store — none of the three things the caption is about.
- **logo_illegible (major):** dark wordmark on the dark green floor, measured **2.69:1**.
- **logo_misplaced (major):** the pale wall immediately above measured **6.77:1** and was not used.

**`e75139fe-3a77-4748-a70a-782126e78b2d` — "Proof first, before we open"** (facebook, 1536×1024) — **BLOCKER**
- **empty_frame (blocker):** a bare grey-green wall, palm fronds at the left, a shaft of light. The
  headline literally promises *proof* and the frame contains zero proof — no pack, no AB/Eurofeuille
  mark, no shelf, no certification of any kind. The brief did ask for "certification marks, curated
  product rows"; none of it was rendered.
- Logo bottom-right and headline are both legible; the failure is entirely conceptual.
- *(The vision model passed this one. I am overriding it — this is a placeholder background, not a post.)*

**`fb1295e3-b1ee-42de-af20-4f72621ca988` — "Real brands, real organic proof"** (instagram, 1024×1024) — MAJOR
- **logo_illegible (major):** dark-ink wordmark on the dark grey-green tabletop, contrast **1.74–3.27**
  across the entire wordmark (mean 2.15:1) — below the 3:1 floor everywhere, not just in patches. The
  pale wall on the right measured **4.06–7.24** and was unused. This is the worst logo contrast in the batch.
- **hallucinated_text (minor):** the Argiletz tube reads *"Ail skin types"* (should be "All"), and the
  round seal is garbled — *"PRODUIT NATURCLLE / NATURAL PRODUC CLAI"*. Small print, but wrong.
- Otherwise strong: clean composition, and the pack matches the captioned *Argiletz, Green Clay Tube, 150g*
  including the "150 g / 5.29 oz" weight.

**`fc11c08e-bc11-4edc-8751-ad62bde5f86f` — "Three steps to certified organic clarity"** (facebook, 1536×1024) — MAJOR
- **anatomy_artefact (major):** the mother's hands supporting the toddler are malformed. At 1:1 the
  fingers of the two hands fuse into each other, the digit count is ambiguous, and there is a black
  blob where a finger should be. It is the visual centre of the frame.
- Everything else is excellent: real people, food truck, lagoon, logo top-right on sky (crisp),
  headline top-left in a pill. Worth regenerating rather than discarding.

**`6c09662c-0360-438f-b881-c4d30057b333` — "Clearer organic pantry choices, honestly"** (facebook, 1536×1024) — MAJOR
- **wrong_product (major):** the Côteaux Nantais apricot jam jar on the table reads **"260 g"**; the
  caption and the linked product say **690g**. Brand, product type and certification marks are all
  correct — only the size is wrong. For a brand positioned on "verify instead of guessing what bio
  means", shipping a pack that contradicts its own caption is an own-goal.
- Otherwise a beautiful frame: real hero product, logo top-right on a clean pale background, headline
  in a light pill, label text ("CÔTEAUX NANTAIS / au rythme du vivant / CONFITURE D'ABRICOTS / EXTRA /
  Cultivés en agriculture BIOLOGIQUE / AB") all real and correctly spelled.

**`36324dcb-43da-4e67-ab1b-ec4fdb9a2f6a` — "7 days to certified organic clarity"** (instagram, 1024×1024) — MAJOR
- **empty_frame (major):** a wooden fence, a shrub, a rock and an empty green wall. No aisles, no
  shelves, no certification marks — none of what the brief asked for or the caption promises.
- **other / typography (minor):** this is the **only** item of the 16 set in a serif face; the other 15
  use the Poppins geometric sans. Side by side in the calendar the set does not read as one campaign.
- Logo bottom-right measured 4.52:1 — legible, no defect there.

**`59f65afc-ea99-4220-9ff6-fdbee5de4d7c` — "Two new organic doors, clearly certified"** (instagram, 1024×1024) — MAJOR
- **empty_frame (major):** the copy's metaphor was rendered literally — two actual pale-green garden
  doors standing open in an empty room. "Two new doors" meant two new stores. There is no store, no
  shelf, no product and no certification anywhere in the frame, so "clearly certified" is unsupported
  by anything visible.
- Logo bottom-right measured 5.66:1 and the headline is clean — this is purely a concept failure.

**`67eebc57-e937-4142-8cda-1202ba59126b` — "Opening tomorrow, certified from the start"** (instagram, 1024×1024) — MAJOR
- **other / brand-claim risk (major):** a woman in a grower's apron standing in a cultivated field
  with the Mauritian mountains behind her reads unmistakably as *"we grow this / farm-to-table"*.
  Naturespan's own guardrails forbid exactly that: *"NEVER use 'farm-to-table' (no confirmed local farm
  partnerships)"*. The products are French/EU AB + Eurofeuille imports sourced through ACCORD BIO. The
  image asserts visually the claim the copy rules prohibit in words — and image claims are the ones
  regulators and customers react to.
- Technically the frame is excellent: logo top-right on clean sky, headline in a light pill at the
  bottom, no artefacts, palette on-brand. It is the *casting* that is off-brand, not the craft.

---

## Recommended actions

1. **Upload a light/reversed Naturespan logo.** `brand_guidelines->'logos'` has `primary` only, which
   makes `select_logo_variant` a no-op. This single asset fixes the contrast failures on
   `fb1295e3`, `3d18f709` and `0c3d71d9` without any code change.
2. **Stop skipping the branding review on ad posts** (`nodes.py:3120`). Replace the blanket early
   return with a logo-only contrast gate that re-renders the logo when the region falls under 3:1,
   leaving the AI-placed headline untouched.
3. **Let `find_best_logo_position` see the whole frame.** It currently offers only `top-right` and
   `top-left`, so whenever the art-director LLM picks a bottom position nothing scores that region at all.
4. **Require a nameable hero subject when `product_ids` is empty.** All 6 product-linked items
   produced a real subject; 5 of the 10 unlinked ones collapsed into set dressing or a literal metaphor.
5. **Validate `visual_direction` against `item_type` at planning time.** 8 of 16 `post` rows carry
   reel/montage/footage language that a still-image model cannot render.
6. **Re-check rendered pack copy before publish.** `88d92f88` invents fake body copy on a real
   supplier's pack; `6c09662c` and `88d92f88` both show a weight that contradicts the linked product.
