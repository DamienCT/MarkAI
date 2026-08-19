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
