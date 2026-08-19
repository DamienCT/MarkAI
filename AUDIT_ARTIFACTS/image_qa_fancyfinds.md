# Image QA — FancyFinds (brand `44fff7ab-2cb2-4745-9af3-7b4ae51f6bf5`)

Vision audit of every `in_review` calendar item of `item_type = 'post'`.
Date: 2026-08-19. Auditor: vision model `gpt-5.4` via LiteLLM (same call shape as
`backend/app/api/v1/products.py::_image_depicts_product`) **plus a human-equivalent
second pass** — every image was opened and inspected directly, and every vision
verdict below was corrected against what is actually in the pixels. Where the model
and the direct inspection disagreed, the direct inspection wins (the model produced
at least one self-contradictory verdict; see item 1).

Asset audited per item: `content.generation_metadata->>'generated_image_url'`
→ `content-images/<brand_id>/<calendar_item_id>/branded.png` (the composited file
the app actually displays).

## Scoreboard

| # | Item | Channel | Verdict |
|---|------|---------|---------|
| 1 | Segafredo quality for calm morning hosting | linkedin | **REJECT** — headline buried the hero pack |
| 2 | Midweek reset, cup in hand | instagram | **CLEAN** |
| 3 | How do you start your morning slower? | facebook | **CLEAN** |
| 4 | Premium hosting made easy with Citterio | linkedin | PUBLISHABLE (one minor) |
| 5 | Friday board ready for sharing? | facebook | **REJECT** — chocolate staged with cured ham, no board |
| 6 | Friday night, cup in hand | instagram | PUBLISHABLE (two minors) |
| 7 | Weekend board, instantly inviting | instagram | **REJECT** — logo lost + matcha props on an Italian charcuterie post |
| 8 | Brunch starts with the coffee, doesn't it? | facebook | **REJECT** — Segafredo wordmark mangled on the hero pack |
| 9 | Monday deserves espresso and chocolate | instagram | **REJECT** — no chocolate anywhere in frame |
| 10 | Weekend guests coming, board almost ready? | facebook | **REJECT (blocker)** — headline truncated mid-word |

**10 audited · 4 publishable (2 of them genuinely excellent) · 6 need a redo · 1 blocker.**

---

## 1. `20aa5de9-e959-48fc-805a-6419039f12f8` — "Segafredo quality for calm morning hosting" (linkedin, 1536×1024)

**REJECT — major.**

- **Headline buried the hero product (major, `other`).** The composited headline is set
  enormous across the whole frame and the words `calm / morning / hosting` land directly
  on the Segafredo capsule box. The pack's own `Segafredo` wordmark is completely covered
  by the word "calm". The single thing the post sells is hidden behind its own caption.
  The left half of the frame (lake, sky, blurred trees) was empty and would have taken
  the whole headline without touching the pack.
- **Garbled pack micro-text (minor, `hallucinated_text`).** At 100% the pack reads
  `100S ABARCA` where it should read `100% ARABICA`, and the bottom line renders as
  `x10 DOMEKA COUNTIENDU / CONVENTIENS CANGULEED` — gibberish.
- Clean axes: logo (white wordmark bottom-left on dark wood + shadowed foliage) is
  legible and well placed; a real hero subject is present; Segafredo co-brand logo
  bottom-right is crisply rendered; palette (greens, wood, white) is on-brand; no
  anatomy problems; nothing clipped by the frame edge.
- Note: the vision model claimed "the headline does not match the intended text" while
  quoting text identical to the intended line — that verdict is a hallucination and was
  discarded. The real defect is occlusion, not wrong copy.

## 2. `154e5f74-e8e8-446f-8d11-07a905d40030` — "Midweek reset, cup in hand" (instagram, 1024×1024)

**CLEAN — one of the best in the set.**

- Logo: top-right, green tree mark + dark-green `fancy finds / MAURITIUS` on a pale
  blurred wall. Full contrast, clean separation, correct variant for the region.
- Headline: light pill top-left, dark text over blurred palm — legible, tidy, not
  overlapping anything.
- Subject: real hero pack — `Segafredo Le Origini Brasile` bag, correctly rendered
  wordmark, matching the caption's named product. Supported by an espresso glass,
  croissant, citrus bowl, veranda greenery. Genuine premium-lifestyle frame.
- Rendered text: only the pack, and it reads correctly (`Segafredo`, `ZANETTI`,
  `LE ORIGINI`, `BRASILE`, `100% ARABICA`).
- No anatomy issues, nothing clipped, palette on-brand.
- Nitpick, not a defect: a single Nespresso-style capsule sits next to a *ground* coffee
  bag — a format mismatch nobody will notice.

## 3. `d7a40d2c-4580-41e7-89e2-50e509168e5e` — "How do you start your morning slower?" (facebook, 1536×1024)

**CLEAN.**

- Logo: top-right on a flat pale sage wall, dark grey wordmark + green mark, high
  contrast. Correct variant, correct region — this is what the placement logic should
  always do.
- Headline: left third, white with a green `slower?`, over a plain wall and softly
  blurred foliage. Readable at feed size; line breaks are acceptable (the vision model's
  claim that "do" is isolated is wrong — it reads `How do / you start / your morning /
  slower?`).
- Subject: `Segafredo Le Origini Perú` 250g pack on a marble round, matching the
  caption. Segafredo co-brand logo bottom-left is crisp.
- Nitpick, not a defect: the pack's small Italian back-copy is scrawled/garbled, and
  wasabi-coated peas next to Italian ground coffee is an odd pairing. Neither is
  reject-worthy at publication size.

## 4. `66876363-2edd-44c0-8dcd-36180c806394` — "Premium hosting made easy with Citterio" (linkedin, 1536×1024)

**PUBLISHABLE — one minor.**

- **Garbled pack print (minor, `hallucinated_text`).** The pack's diagonal band
  double-prints two strings on top of each other (`PROSCIUTTO DI PARMA` overlaid with a
  smeared `CITTERIO … SPA`), the `14` quality seal's ring text is gibberish, and the
  weight renders as `70 t is e` instead of `70 g e`. Invisible at feed size, obvious at 100%.
- Everything else is strong: headline in a light pill top-left with dark text, fully
  legible over the leafy background; logo top-right on a bright blurred wall, legible;
  hero `CITTERIO Prosciutto di Parma taglio fresco` pack correctly branded and centred;
  olives, cheese board, walnuts, wine — coherent hosting scene; palette on-brand;
  nothing clipped; no anatomy problems.
- **Planning-data defect (not an image defect):** `calendar_items.visual_direction` for
  this item reads *"a plated pasta dish"* while the brief and caption are about a
  prosciutto sharing board. The image followed the caption, so no harm here, but the
  field is wrong at source.

## 5. `8513153e-719b-4ccc-a93c-d591126082d1` — "Friday board ready for sharing?" (facebook, 1536×1024)

**REJECT — major.**

- **Props contradict the caption and break a brand rule (major, `other`).** The caption
  says *"Add crisp toasts, olives, and cheese, then let the board do the hosting"*.
  There is no board, no toasts, no olives and no cheese anywhere in the frame. What is
  actually staged around the Prosciutto di Parma pack: milk-chocolate chunks, chocolate
  truffles, cashews, almonds and pistachios. Chocolate placed directly beside cured ham
  is precisely the brand's own written don't — *"never mix categories that would not
  naturally appear together"*. A headline promising a "board" over a frame with no board
  is a concept failure, not a styling nitpick.
- **Garbled pack print (minor, `hallucinated_text`).** Same Citterio pack family as
  item 4 — diagonal band double-printed, seal micro-text gibberish.
- Acceptable: logo top-right (dark grey/green on mid-green — modest but sufficient
  contrast); headline white with drop shadow, legible; Citterio diamond badge bottom-left
  is correctly rendered (`1878 / CITTERIO / MILANO`) though it sits awkwardly across the
  truffle bowl; hero pack matches the caption's product; no anatomy issues.

## 6. `e3bc681e-34e8-4e7c-b255-c3585e16b1c5` — "Friday night, cup in hand" (instagram, 1024×1024)

**PUBLISHABLE — two minors.**

- **Scene contradicts the headline's time of day (minor, `other`).** Headline is
  "Friday night, cup in hand" and the caption says *"Dim the lights"*. The frame is
  bright, flat daylight, and the cup on the table is empty white ceramic — nobody is
  holding anything and no coffee has been poured. Attractive image, wrong hour.
- **Garbled pack print (minor, `hallucinated_text`).** `Eaprcceo INTENSO` for
  `Espresso INTENSO`; `x10 CAPEULE COMPATIRILI` for `CAPSULE COMPATIBILI`.
- Strong otherwise: `Segafredo ZANETTI Intenso` capsule box correctly branded and
  matching the caption; headline in a dark pill top-right, white text on plain wall,
  fully legible; logo directly beneath it on the same clean wall, legible; palette warm
  wood/cream/green, on-brand; nothing clipped; no anatomy issues.

## 7. `63dcde2c-39cb-4d99-a340-c38305eafe7e` — "Weekend board, instantly inviting" (instagram, 1024×1024)

**REJECT — two major defects.**

- **Logo dropped in the worst available region (major, `logo_misplaced`).** The
  FancyFinds mark is composited bottom-left onto the pale stone tabletop, in a light
  grey-green at watermark faintness, with a soft shadow gradient running through it.
  `MAURITIUS` all but disappears; the wordmark reads only just. Meanwhile the entire
  upper-left third of the frame is a flat, clean, unbroken olive-green wall — the
  headline only occupies the upper *right*. A perfect region was available and was not
  chosen. This is the same failure class as the confirmed Naturespan "One week to shop
  with ease" case.
- **Props belong to a different cuisine (major, `other`).** The caption lists
  "Crisp toasts / Olives / Roasted nuts" and the headline promises a "Weekend board".
  The frame contains: a bowl of green matcha powder, a rolled bamboo tea mat, and a cup
  of green tea — Japanese tea-ceremony staging around an Italian `San Daniele`
  prosciutto tray. No board, no toasts, no olives, no nuts.
- **Garbled pack print (minor, `hallucinated_text`).** Diagonal reads
  `PROSCIUTTO DI SAN DANIPLE`; back-of-pack copy and a fake QR block are mush; weight
  renders `70e`.
- Fine: headline upper-right, white with a green `inviting`, over flat wall — clearly
  legible; Citterio diamond badge bottom-right is correctly rendered; palette on-brand;
  no anatomy issues; nothing clipped.

## 8. `6a9f144a-119a-41e0-b24d-95d858f1d974` — "Brunch starts with the coffee, doesn't it?" (facebook, 1536×1024)

**REJECT — major.** Painful, because everything except the pack is excellent.

- **Partner brand's wordmark is mangled on the hero pack (major, `hallucinated_text`).**
  The capsule box front-and-centre on the table shows a broken `Segafredo` wordmark —
  the letterforms collapse into `Sɓɣɑʃɾɐʊʋ`-style mush — the `ZANETTI` line is
  illegible, and `100% ARABICA` renders as `1B%AЯA&ЯICA`. This is the caption's named
  hero product with its trademark rendered wrong; the vision model, reading it cold,
  concluded it was a *different brand's* pack. That is exactly the reaction a client will
  have. Third-party trademarks rendered incorrectly are a brand-safety issue, not just an
  aesthetic one.
- **Sweet fruit staged against cured meat (minor, `other`).** A cake stand of green and
  red grapes plus a bowl of berries sits directly against the plate of prosciutto — the
  brand's written don't.
- Genuinely excellent otherwise, and close to the gold-standard reference: four real
  people at a real brunch table, natural expressions, correct hands and faces, moka pot,
  espresso glasses, breads, palms. Logo top-right on a plain wall, crisp and legible.
  Headline in a dark translucent pill across the bottom, white, fully readable over a
  busy table. Palette warm and on-brand. Nothing clipped. **Fix the pack and this is a
  publish.**

## 9. `83ce6820-e4e5-476c-b4b2-236dd1ed3a12` — "Monday deserves espresso and chocolate" (instagram, 1024×1024)

**REJECT — major.**

- **The headline names something that is not in the frame (major, `other`).** The
  composited headline reads "Monday deserves espresso and chocolate" and the caption
  builds the whole post on World Chocolate Day (*"Pair it with a square of dark
  chocolate or a cocoa biscuit"*). There is no chocolate in the image. The only food
  besides the capsule box is a bowl of green plums/greengages. Note the mirror-image of
  item 5, where chocolate turned up in a *prosciutto* post.
- **Client's own logo is the faintest element on the frame (minor, `logo_illegible`).**
  Bottom-left, grey-green at watermark opacity on a pale-green surface. It reads, but
  barely — while the *Segafredo* logo bottom-right on the same surface is bold red and
  black and visually dominates it. On a FancyFinds channel the distributor's mark should
  not be the weakest thing in the frame.
- **Headline typography (minor, folded in).** Line sizes jump wildly — "Monday" small,
  "chocolate" huge and running almost into the right edge. Reads auto-fitted, not
  art-directed.
- Fine: `Segafredo ZANETTI Espresso Intenso` pack correctly branded and matching the
  caption; clean studio composition; palette on-brand; no anatomy issues; nothing clipped.

## 10. `d7e7aae0-bfc6-4ca7-87b3-4cb05937b911` — "Weekend guests coming, board almost ready?" (facebook, 1536×1024)

**REJECT — BLOCKER.**

- **Headline truncated mid-word (blocker, `crop_or_clipping`).** The composited headline
  reads `Weekend guests coming, board almost read…` — cut off with an ellipsis where it
  should read `…board almost ready?`. This is an automatic reject: no client publishes a
  post whose headline stops mid-word. It points at the single-line pill layout having no
  wrap path and falling back to ellipsis truncation.
- **Hero pack label is mirrored (major, `hallucinated_text`).** The red `CITTERIO` flash
  on the tub is printed back-to-front — it reads `OIЯƎTTIƆ`. The pack is also a generic
  clear plastic tub rather than the named `Citterio Salami Napoli 150g` retail pack.
- **Sweet fruit against cured meat (minor, `other`).** A large platter of green grapes
  sits immediately beside the charcuterie board — the brand's written don't.
- Fine: logo top-right on a bright blurred background, crisp and legible (the headline
  pill does crowd it); real, well-lit food scene with genuine texture; the hand holding
  the knife is anatomically acceptable; palette warm and on-brand. Loose composition —
  the bottom ~35% is empty table — but usable.

---

## Systemic findings (what to fix in the pipeline, not item by item)

1. **Headline fitting has two opposite failure modes, from the same overlay code.**
   Item 1 sets the headline so large it covers the hero product; item 10 truncates the
   headline with an ellipsis. Both come out of `overlay_logo_and_text` in
   `agents/shared/image_processing.py`. Two distinct layout styles are in play — a large
   multi-line white-with-drop-shadow treatment (items 1, 3, 5, 7, 9) and a single-line
   dark/light pill (items 2, 4, 6, 8, 10) — and it is the pill style that truncates.
   Neither style is subject-aware: nothing stops the type from being placed on the pack.
   **Fix: (a) never allow the headline box to intersect the detected product region;
   (b) the pill style must wrap to a second line instead of ellipsising.**

2. **Logo variant/opacity selection degrades on mid-tone and pale surfaces.** Where the
   logo lands on a plain bright wall (items 3, 4, 6, 8, 10) it is crisp and correct.
   Where it lands on a tabletop or a tinted surface (items 7, 9) it is composited at
   watermark faintness and reads weakly. In item 7 a large flat clean wall was available
   upper-left and was not used — the same failure as the confirmed Naturespan case. The
   region scoring is favouring "low local variance" (an empty tabletop) over "high
   contrast against the chosen logo variant". **Fix `find_best_logo_position` /
   `analyze_logo_region_brightness` to score candidate regions on the contrast the
   *selected variant* would actually achieve, and stop compositing at watermark opacity
   on the brand's own channel.**

3. **Prop selection is decoupled from the caption — and props are landing on the wrong
   items.** The accompaniments the caption explicitly names never reach the image prompt:
   item 5 promises toasts/olives/cheese and gets chocolate and nuts; item 7 promises
   toasts/olives/nuts and gets matcha and a bamboo mat; item 9 promises chocolate and
   gets green plums. Chocolate showed up in the *prosciutto* post and was missing from
   the *chocolate* post. This also drives straight through the brand's own written don't
   about mixing sweet items with cured meat (items 5, 8, 10). **Fix: pass the caption's
   named accompaniments into the image prompt as required props, and inject the brand
   `donts` about category mixing as negative constraints.**

4. **Partner-brand pack lettering is the biggest single quality risk.** The model renders
   the large marks (`SEGAFREDO`, `CITTERIO`, `taglio fresco`, `PARMA`) convincingly most
   of the time, but garbles small print on *every single pack in the set*, mangles the
   main wordmark outright in item 8, and mirrors it in item 10. For a distributor whose
   whole proposition is representing real third-party brands, a garbled or reversed
   partner trademark is a legal and relationship risk. **Fix: composite the real pack
   shot (products already carry images) rather than asking the image model to draw a
   trademark, or add a post-generation OCR check on the pack region against the expected
   brand string.**

5. **Brief/caption product drift.** Several `content_brief` values name a different SKU
   from the published caption (brief: "Capsules Classico Espresso Alu" → caption:
   "Le Origini Brasile Ground" / "Le Origini Peru Ground" / "Capsules Intenso"). Items 4,
   5 and 10 also have an empty `product_ids` join to a name, and item 4's
   `visual_direction` asks for "a plated pasta dish" on a prosciutto post. The images
   followed the captions, so nothing broke visually, but the planning layer is
   internally inconsistent.

6. **No empty-frame defects in this brand.** Unlike the confirmed Naturespan case, all
   ten FancyFinds frames have a real hero subject — a branded pack, and in item 8 real
   people. Whatever is producing content-empty set-dressing elsewhere is not firing on
   these briefs. Items 2, 3 and 8 (pack aside) are at or near the gold-standard bar.
