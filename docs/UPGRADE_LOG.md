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
