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
