# MARKAI — World-Class Content Engine: Implementation Plan

## Current State Assessment

**Functional but not world-class.** The pipeline works end-to-end but wastes 97% of available LLM context and siloes data between stages.

| Problem | Impact |
|---------|--------|
| Prompts truncate context to 500-3000 chars | GPT-5.4 supports ~1M tokens — we're using <3% of capacity |
| Strategy document never reaches content generation | Captions are written without strategic context |
| Research personas ignored by strategy audiences | Two disconnected audience definitions across documents |
| Content pillars invisible to caption/hook/hashtag writers | Posts don't align with pillar distribution |
| Zero deduplication | Same topic can repeat within a week |
| Competitor data is name + website only | No competitive intelligence in content differentiation |
| Product data absent from content prompts | Product posts have no benefit/feature context |
| Engagement metrics never fed back to content | No learning from what works |
| Brand colors/fonts/visual style not in image prompts | Generated images don't match brand identity |

---

## Architecture: Before vs After

```
BEFORE (siloed, truncated):
  Research → [save output_payload] → Strategy → [save output_payload] → Planning → [save output_payload]
  Content ← loads: brand name, theme, channel, brand_voice (truncated to 2000 chars)

AFTER (unified, full context):
  Research → Strategy → Planning → all save to agent_runs
  Content ← loads: BrandIntelligence package (ALL data from all 3 stages + engagement history + products + brand guidelines)
  Every prompt gets: full positioning, relevant pillar, target audience, monthly theme, product details, recent posts, strategy document excerpt
```

---

## Phase 1: Brand Intelligence Package

### What

A single function `build_brand_intelligence(brand_id)` that consolidates ALL available data into one object. Every workflow loads this instead of making scattered queries.

### Data Structure

```python
BrandIntelligence = {
    # ── Brand Identity ──
    "brand": {
        "name": str,
        "description": str,
        "website_url": str,
        "industry": str,
        "tone_of_voice": str,       # free-text voice description
        "brand_guidelines": {
            "colors": {"primary": "#hex", "secondary": "#hex", "accent": "#hex"},
            "fonts": {"heading": str, "body": str},
            "visual_style": str,     # e.g., "modern, clean, tropical warmth"
            "logos": {"primary": "url", "secondary": "url"},
            "channels": {
                "instagram": {"enabled": True, "handle": "@medactiv.mu", "configured": True},
                # ...per channel config with credentials
            }
        },
        "enabled_channels": ["instagram", "facebook", "linkedin"],
        "products": [               # from BC sync — active products
            {"name": str, "sku": str, "category": str, "vendor": str,
             "unit_price": float, "description": str, "primary_image_url": str,
             "is_new": bool, "is_expiring_soon": bool, "remaining_qty": int}
        ]
    },

    # ── Research Intelligence (latest completed) ──
    "research": {
        "personas": [               # SOURCE OF TRUTH for audience references
            {"name": str, "demographics": {}, "psychographics": str,
             "pain_points": [], "content_preferences": {"formats": [], "topics": [], "tone": str, "language_mix": str},
             "platforms": [], "buying_triggers": [], "best_engagement_times": str}
        ],
        "competitors": [
            {"name": str, "website_url": str, "positioning": str,
             "strengths": [], "weaknesses": [], "social_presence": {},
             "content_strategy": str, "threat_level": str}
        ],
        "gaps": [
            {"title": str, "category": str, "description": str, "opportunity": str,
             "priority": str, "estimated_impact": str, "target_audience": str}
        ],
        "social_analysis": {}       # platform performance, engagement rates, peak times
    },

    # ── Strategy (latest completed) ──
    "strategy": {
        "positioning": {
            "value_proposition": str, "differentiators": [], "brand_voice": str,
            "tone_attributes": [], "key_messages": [], "brand_archetype": str
        },
        "pillars": [
            {"name": str, "description": str, "percentage": int,
             "audience_alignment": [str], "example_topics": [], "visual_style": str}
        ],
        "audiences": [              # cross-referenced with research personas
            {"segment_name": str, "persona_ref": str, "platforms": [],
             "content_preferences": str, "engagement_strategy": str}
        ],
        "cadence": {},              # per-platform posting schedule
        "themes": [                 # monthly themes with weekly sub-themes
            {"month": str, "theme_name": str, "sub_themes": [],
             "key_dates": [], "pillar_focus": str}
        ]
    },

    # ── Planning (latest completed) ──
    "planning": {
        "strategy_document": str,   # FULL year-long markdown — NOT truncated
        "campaigns": [
            {"name": str, "description": str, "start_date": str, "end_date": str,
             "pillar": str, "goal": str, "target_audience": str, "creative_direction": str}
        ]
    },

    # ── Content History (for deduplication) ──
    "recent_posts": [               # last 90 days
        {"title": str, "theme": str, "pillar": str, "channel": str,
         "scheduled_at": str, "caption_snippet": str, "status": str}
    ],

    # ── Engagement Performance (for learning) ──
    "top_performing": [             # top 10 posts by engagement rate, last 90 days
        {"title": str, "channel": str, "engagement_rate": float,
         "likes": int, "comments": int, "caption_snippet": str}
    ]
}
```

### Implementation Details

**File:** `agents/shared/tools/database.py`

```python
async def build_brand_intelligence(brand_id: str) -> dict:
    """Build consolidated context package for all AI workflows."""
    async with async_session_factory() as session:
        # 1. Brand config + products (single query with JOIN)
        brand = await _get_brand_full(session, brand_id)
        products = await _get_active_products(session, brand_id, limit=100)

        # 2. Latest completed research
        research = await _get_latest_run_payload(session, brand_id, "research")

        # 3. Latest completed strategy
        strategy = await _get_latest_run_payload(session, brand_id, "strategy")

        # 4. Latest planning + strategy document
        planning = await _get_latest_run_payload(session, brand_id, "planning")
        strategy_doc_run = await _get_latest_run_payload(session, brand_id, "content_calendar_strategy")

        # 5. Recent posts (last 90 days) for dedup
        recent = await _get_recent_calendar_items(session, brand_id, days=90)

        # 6. Top performing content (for learning)
        top = await _get_top_performing(session, brand_id, limit=10)

        return {
            "brand": {**brand, "products": products},
            "research": research or {},
            "strategy": strategy or {},
            "planning": {
                "strategy_document": (strategy_doc_run or {}).get("document", ""),
                "campaigns": (planning or {}).get("campaigns", []),
            },
            "recent_posts": recent,
            "top_performing": top,
        }
```

**Key design decisions:**
- Products capped at 100 (top by remaining_qty) — enough for context, not overwhelming
- Recent posts = 90 days (full quarter for dedup)
- Top performing = 10 posts with highest engagement_rate — teaches the LLM what works
- strategy_document is NEVER truncated when loaded — only when injected into prompts, and even then we give it 20K+ chars (GPT-5.4 can handle it)

---

## Phase 2: Enriched Research Prompts

### What Changes

The research workflow prompts get richer output schemas and the competitor analysis does actual competitive intelligence, not just name discovery.

### Competitor Analysis — Before vs After

**Before (nodes.py ~line 121):**
```
"identify their top 5 LOCAL competitors. Return JSON array with 'name' and 'website' fields."
```

**After:**
```
"Identify their top 5 LOCAL competitors in Mauritius. For EACH competitor, provide a comprehensive profile.
Return JSON array where each object has:
- name: Company name
- website_url: Their website
- positioning: Their brand positioning statement (1 sentence)
- strengths: Array of 3+ competitive strengths
- weaknesses: Array of 3+ competitive weaknesses
- social_presence: Object with platform names as keys, estimated follower counts as values
- content_strategy: Description of their social media content approach (frequency, content types, tone)
- threat_level: 'high', 'medium', or 'low' based on market overlap and competitive strength"
```

### Gap Analysis — Before vs After

**Before:**
```
"Return JSON array with 'category', 'description', 'opportunity', 'priority' fields."
```

**After:**
```
"Return JSON array where each gap has:
- title: Short descriptive title
- category: One of: content, positioning, digital, audience, product, channel
- description: What the gap is
- opportunity: How to exploit it
- priority: high/medium/low
- estimated_impact: Expected business impact if addressed
- implementation_effort: low/medium/high
- recommended_timeline: When to implement (e.g., 'Q2 2026')
- target_audience: Which persona(s) this gap affects most
- success_metrics: Array of 2-3 measurable KPIs to track"
```

### Persona — Before vs After

**Before:**
```
"Each persona should have: name, demographics, psychographics, pain_points, content_preferences, platforms, buying_triggers."
```

**After:**
```
"Each persona should have:
- name: A memorable name and archetype (e.g., 'Priya, the Wellness Enthusiast')
- demographics: Object with age range, gender, location (Mauritian city), income level, education, occupation
- psychographics: Values, lifestyle, interests, media habits
- pain_points: Array of 3+ specific pain points related to the brand's industry
- content_preferences: Object with:
  - formats: Preferred content formats (Reels, Carousels, Stories, Static, Articles)
  - topics: 5+ specific topic interests
  - tone: Preferred communication tone
  - language_mix: English/French/Kreol preference and ratio
- platforms: Array of social platforms they use, ordered by preference
- buying_triggers: Array of 3+ triggers that drive purchase decisions
- best_engagement_times: Specific times in GMT+4 when this persona is most active
- content_avoidance: What turns this persona off (e.g., 'hard sells', 'medical jargon')"
```

### Social Analysis — Enriched

**After prompt addition:**
```
"Include in your analysis:
- engagement_rate: Current average engagement rate as a percentage
- benchmark_comparison: How this compares to industry average in Mauritius (health/wellness: ~2.1%)
- top_content_types: Ranked list of content types by engagement (Reel > Carousel > Static, etc.)
- peak_times: Best posting times per platform in GMT+4 with data-backed reasoning
- content_gaps: What competitors post about that this brand doesn't
- hashtag_analysis: Top 10 hashtags by reach from recent posts
- recommendations: 5 specific, actionable recommendations"
```

---

## Phase 3: Enriched Strategy Prompts

### Positioning — Add brand archetype + competitive matrix

**After prompt addition:**
```
"Also include:
- brand_archetype: The brand's Jungian archetype (e.g., Caregiver, Sage, Creator)
- emotional_territory: The emotional space the brand owns
- competitive_differentiation: Object comparing this brand vs top 3 competitors across 5 dimensions:
  {dimension: str, brand_score: 1-5, competitor_scores: {name: 1-5}}"
```

### Pillars — Add audience + seasonal alignment

**After prompt addition:**
```
"Each pillar should also include:
- audience_alignment: Array of persona names this pillar primarily serves
- seasonal_emphasis: Which months/quarters this pillar gets more weight
- platform_fit: Which platforms are best for this pillar's content
- visual_style: Visual direction for this pillar (colors, mood, photography style)
- pillar_rationale: Why this pillar matters for this brand's strategic goals"
```

### Audiences — Cross-reference research personas

**Critical change:** Pass research personas into the prompt explicitly.

```python
# In define_audiences():
personas_context = sanitize_json_for_prompt(state.get("research_data", {}).get("personas", []), max_length=6000)

prompt = [
    {"role": "system", "content": "...Define 3-5 target audience segments. "
     "IMPORTANT: These segments MUST cross-reference the research personas below. "
     "Each segment must include a 'persona_ref' field naming which research persona(s) it aligns with. "
     "Do NOT invent new audiences that contradict the research personas..."},
    {"role": "user", "content": (
        f"Research Personas (source of truth):\n{personas_context}\n\n"
        f"Positioning:\n{...}\n\nPillars:\n{...}"
    )},
]
```

### Themes — Full year, week-by-week

**Before:** 3 months of themes
**After:** 12 months with weekly sub-themes

```
"Generate monthly themes for ALL 12 months starting from the current date.
Each month should have:
- month: Month name and year
- theme_name: Overarching theme
- sub_themes: Array of 4 weekly sub-themes, each with:
  - week: 'W1', 'W2', 'W3', 'W4'
  - focus: Sub-theme name
  - pillar: Which content pillar this week emphasizes
  - primary_audience: Which persona to prioritize this week
- key_dates: Array of dates in this month with:
  - date: Date string
  - event: Event name (Mauritius holidays, global awareness days, industry events)
  - content_angle: Specific angle for this date
  - format: Recommended content format
  - audience: Target persona
- pillar_rotation: How pillars rotate across the 4 weeks"
```

### Strategy Document — Increased output tokens

```python
# In generate_campaigns(), for strategy_document generation:
strategy_document = await chat_completion(strategy_doc_prompt, temperature=0.6, max_tokens=16384)
```

**Why 16384:** The strategy document is the master reference for all content generation. With GPT-5.4's capacity, we can afford a detailed 12-month guide. Current 4096 limit produces a thin document.

---

## Phase 4: Enriched Planning Prompts

### Calendar Items — Richer structure

**Before:** `campaign_name, scheduled_date, platform, content_type, theme, product_name, brief`

**After:**
```
"Each calendar item must include:
- campaign_name: Which campaign this belongs to
- scheduled_date: YYYY-MM-DD
- platform: Channel name
- content_type: post/reel/story/carousel/article
- pillar: Which content pillar (from strategy)
- theme: Monthly theme name
- weekly_sub_theme: Specific sub-theme for this week
- target_audience: Primary persona for this post
- content_brief: 2-3 sentences describing EXACTLY what this post should communicate
- product_name: Product to feature (null if lifestyle/educational)
- visual_direction: 1 sentence on visual style for the image
- cta_type: What action to drive (shop, learn, engage, share)"
```

### Calendar Deduplication

**New:** Before generating calendar items, load existing items for overlap detection.

```python
# In generate_calendar():
existing_items = await get_recent_calendar_items(brand_id, days=scope_weeks * 7 + 30)
existing_summary = [
    f"{i['scheduled_at'][:10]} | {i['channel']} | {i.get('theme', i.get('title', ''))}"
    for i in existing_items[:50]
]

# Add to prompt:
f"EXISTING CALENDAR ITEMS (do NOT duplicate themes or topics):\n" +
"\n".join(existing_summary)
```

### Campaign Target Metrics

**After:**
```
"Each campaign should also include:
- target_metrics: Object with baseline and target for: reach, engagement_rate, link_clicks, conversions
- creative_direction: 2-3 sentences describing the visual/tonal approach
- content_format_mix: Object with content_type percentages (e.g., {reel: 40, carousel: 30, static: 20, story: 10})
- target_audience: Primary persona name from strategy"
```

---

## Phase 5: Content Prompt Enrichment

### The Big Change

Every content generation node receives `BrandIntelligence` via `load_context`. The prompts are then constructed with rich, relevant context — not truncated summaries.

### load_context — Rewritten

```python
async def load_context(state: ContentState) -> dict:
    brand_id = state["brand_id"]
    item_id = state["calendar_item_id"]

    # Load the full intelligence package
    intel = await build_brand_intelligence(brand_id)
    calendar_item = await get_calendar_item(item_id)

    if not intel.get("brand") or not calendar_item:
        return {"status": "failed", "errors": ["Brand or calendar item not found"]}

    # Transition to working
    await execute_update(
        "UPDATE calendar_items SET status = 'working' WHERE id = :id AND status = 'queued'",
        {"id": item_id},
    )

    # Find the relevant pillar, audience, and monthly theme for THIS post
    pillar_name = calendar_item.get("pillar", "")
    audience_name = calendar_item.get("target_audience", "")
    theme = calendar_item.get("theme", calendar_item.get("title", ""))

    relevant_pillar = next(
        (p for p in intel.get("strategy", {}).get("pillars", []) if p.get("name", "").lower() == pillar_name.lower()),
        {}
    )
    relevant_audience = next(
        (a for a in intel.get("research", {}).get("personas", []) if audience_name.lower() in a.get("name", "").lower()),
        {}
    )

    # Extract current month's strategy document section
    strategy_doc = intel.get("planning", {}).get("strategy_document", "")
    current_month = datetime.now().strftime("%B")
    # Find the section for this month (rough extraction)
    month_section = _extract_month_section(strategy_doc, current_month)

    return {
        "brand": intel["brand"],
        "calendar_item": calendar_item,
        "strategy": intel.get("strategy", {}),
        "positioning": intel.get("strategy", {}).get("positioning", {}),
        "relevant_pillar": relevant_pillar,
        "relevant_audience": relevant_audience,
        "month_context": month_section,
        "recent_posts": intel.get("recent_posts", []),
        "top_performing": intel.get("top_performing", []),
        "product": _find_product(intel["brand"].get("products", []), calendar_item),
    }
```

### Hook Prompt — Before vs After

**Before (5 context fields):**
```
Brand name, Platform, Content type, Theme, Brand voice
```

**After (15+ context fields):**
```python
prompt = [
    {"role": "system", "content": (
        "You are an expert social media copywriter for the Mauritian market. "
        "Write a scroll-stopping hook (opening line) for a social media post. "
        "The hook must be under 15 words, emotionally compelling, and aligned with the brand voice. "
        "Naturally weave in French or Kreol Morisien phrases where they add warmth and local resonance. "
        "Return ONLY the hook text."
    )},
    {"role": "user", "content": (
        f"BRAND: {brand['name']}\n"
        f"BRAND VOICE: {positioning.get('brand_voice', '')}\n"
        f"BRAND ARCHETYPE: {positioning.get('brand_archetype', '')}\n\n"
        f"THIS POST:\n"
        f"  Platform: {item.get('channel')}\n"
        f"  Content type: {item.get('content_type', item.get('item_type', ''))}\n"
        f"  Theme: {item.get('theme', '')}\n"
        f"  Sub-theme: {item.get('weekly_sub_theme', '')}\n"
        f"  Brief: {item.get('content_brief', item.get('description', ''))}\n"
        f"  Pillar: {relevant_pillar.get('name', '')}\n\n"
        f"TARGET AUDIENCE: {relevant_audience.get('name', '')}\n"
        f"  Pain points: {', '.join(relevant_audience.get('pain_points', []))}\n"
        f"  Tone preference: {relevant_audience.get('content_preferences', {}).get('tone', '')}\n\n"
        f"PRODUCT (if applicable): {product.get('name', 'N/A')} — {product.get('description', '')}\n\n"
        f"RECENTLY POSTED HOOKS (do NOT repeat similar openings):\n"
        f"{chr(10).join(f'- {p.get(\"caption_snippet\", \"\")[:60]}' for p in recent_posts[:10])}\n\n"
        f"TOP PERFORMING HOOKS (learn from these):\n"
        f"{chr(10).join(f'- {p.get(\"caption_snippet\", \"\")[:60]} (engagement: {p.get(\"engagement_rate\", 0):.1%})' for p in top_performing[:5])}"
    )},
]
```

### Caption Prompt — After

Same pattern: full positioning, pillar description, audience pain points + content preferences, product benefits, strategy document month excerpt, recent captions to avoid, top performing captions to learn from, explicit CTA guidance.

**Key addition — strategy document context:**
```python
f"STRATEGY GUIDANCE FOR THIS MONTH:\n{month_context[:5000]}\n\n"
```

This gives the caption writer the strategic narrative for the current month — what themes to emphasize, what events to reference, what tone to strike.

### Hashtag Prompt — After

```python
f"FULL CAPTION:\n{state.get('caption', '')}\n\n"  # No more 500-char truncation
f"PLATFORM LIMITS: {'30 hashtags max' if channel == 'instagram' else '3-5 hashtags' if channel == 'linkedin' else '5-10 hashtags'}\n"
f"BRAND'S TOP HASHTAGS (from past engagement data):\n{top_hashtags}\n"
f"COMPETITOR HASHTAGS:\n{competitor_hashtags}\n"
f"ALWAYS INCLUDE: #{brand_name_slug}, #Mauritius, #IleMaurice\n"
```

### Background Image Prompt — After

```python
f"Brand color palette: Primary {colors.get('primary', '#3b82f6')}, "
f"Secondary {colors.get('secondary', '#22c55e')}, "
f"Accent {colors.get('accent', '#f59e0b')}.\n"
f"Visual style: {brand_guidelines.get('visual_style', 'modern, clean, tropical warmth')}.\n"
f"Target audience aesthetic: {relevant_audience.get('content_preferences', {}).get('tone', 'aspirational')}.\n"
f"Seasonal direction: {month_context[:200] if month_context else 'current season in Mauritius'}.\n"
```

### Platform Adaptation Prompt — After

Add full positioning and audience context:
```python
f"BRAND POSITIONING: {positioning.get('value_proposition', '')}\n"
f"BRAND VOICE: {positioning.get('brand_voice', '')}\n"
f"KEY MESSAGES: {', '.join(positioning.get('key_messages', []))}\n"
f"TARGET AUDIENCE: {relevant_audience.get('name', '')} — {relevant_audience.get('content_preferences', {}).get('tone', '')}\n"
f"BRAND URL: {brand.get('website_url', '')}\n\n"
```

---

## Phase 6: Database Schema Changes

### calendar_items — New columns

```sql
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS pillar VARCHAR(100);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS theme VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS target_audience VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS weekly_sub_theme VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS content_brief TEXT;
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS visual_direction TEXT;
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS cta_type VARCHAR(50);
```

### store_calendar_items() — Updated

The function already inserts items — just add the new fields to the INSERT statement and parameter mapping.

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_calendar_items_theme ON calendar_items (theme);
CREATE INDEX IF NOT EXISTS idx_calendar_items_pillar ON calendar_items (pillar);
CREATE INDEX IF NOT EXISTS idx_calendar_items_brand_scheduled ON calendar_items (brand_id, scheduled_at DESC);
```

---

## Phase 7: Token Budget Management

With GPT-5.4 (~1M token context), we have enormous capacity. But we should still be intentional:

| Prompt Section | Token Budget | Notes |
|----------------|-------------|-------|
| System prompt | ~500 | Role + instructions + output schema |
| Brand identity | ~500 | Name, voice, archetype, key messages |
| Positioning | ~800 | Full positioning object |
| Relevant pillar | ~300 | Just the one pillar for this post |
| Target audience | ~400 | Just the one persona for this post |
| Product details | ~200 | Name, description, benefits |
| Strategy month excerpt | ~5,000 | Current month section from strategy doc |
| Recent posts (dedup) | ~2,000 | Last 30 items, title + snippet |
| Top performing | ~1,000 | 10 posts with engagement data |
| Calendar item brief | ~200 | The specific post brief |
| **Total input** | **~11,000** | ~3% of GPT-5.4 capacity |
| **Output budget** | **4,096-16,384** | Depending on node (caption vs strategy doc) |

We have massive headroom. No need for aggressive truncation.

### max_tokens by Node

| Node | Current | After |
|------|---------|-------|
| Research: competitor analysis | 4096 | 8192 |
| Research: gaps, personas | 4096 | 4096 |
| Strategy: positioning, pillars, audiences, cadence | 4096 | 4096 |
| Strategy: themes (12 months) | 4096 | **8192** |
| Planning: campaigns | 4096 | 4096 |
| Planning: strategy_document | 4096 | **16384** |
| Planning: calendar items | 8192 | **16384** |
| Content: hook | 4096 | 256 |
| Content: caption | 4096 | 2048 |
| Content: hashtags | 4096 | 512 |
| Content: adapt_platforms | 4096 | 8192 |

---

## Phase 8: Frontend Report Rendering

### Files to Update

| File | Change |
|------|--------|
| `frontend/src/app/intelligence/report/[id]/page.tsx` | Render enriched competitor cards, gap cards with impact/effort, persona cards with content preferences, competitive matrix table |
| `frontend/src/app/intelligence/page.tsx` | Summary cards show richer previews (competitor threat levels, pillar percentages, audience-pillar cross-reference) |
| `frontend/src/components/content/CalendarView.tsx` | Calendar items show pillar badge, audience tag, content brief tooltip |
| `frontend/src/components/content/ContentCard.tsx` | Show pillar, audience, and brief context |

---

## File Change Matrix

| File | Phase | Changes |
|------|-------|---------|
| `agents/shared/tools/database.py` | 1 | `build_brand_intelligence()`, `get_recent_calendar_items()`, `get_top_performing()` |
| `agents/workflows/research/nodes.py` | 2 | Enriched prompts for competitors, gaps, personas, social analysis |
| `agents/workflows/strategy/nodes.py` | 3 | Personas cross-ref, pillar audience alignment, 12-month themes, competitive matrix |
| `agents/workflows/planning/nodes.py` | 4 | Enriched calendar items, dedup context, campaign metrics, max_tokens increases |
| `agents/workflows/content/nodes.py` | 5 | Full BrandIntelligence in load_context, enriched prompts for all 5 nodes |
| `agents/shared/llm.py` | 7 | Configurable max_tokens per call |
| `db/init.sql` | 6 | New columns on calendar_items |
| `backend/app/models/calendar_item.py` | 6 | New fields: pillar, theme, target_audience, content_brief, etc. |
| `backend/app/schemas/calendar_item.py` | 6 | Match model fields |
| `backend/app/scheduler/morning_jobs.py` | 5 | Top-up includes strategy context |
| `frontend/src/app/intelligence/report/[id]/page.tsx` | 8 | Render enriched reports |
| `frontend/src/app/intelligence/page.tsx` | 8 | Richer preview cards |
| `frontend/src/components/content/CalendarView.tsx` | 8 | Pillar badges, audience tags |

---

## Migration for Existing Deployments

```sql
-- New calendar_items columns
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS pillar VARCHAR(100);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS theme VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS target_audience VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS weekly_sub_theme VARCHAR(255);
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS content_brief TEXT;
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS visual_direction TEXT;
ALTER TABLE calendar_items ADD COLUMN IF NOT EXISTS cta_type VARCHAR(50);
CREATE INDEX IF NOT EXISTS idx_calendar_items_theme ON calendar_items (theme);
CREATE INDEX IF NOT EXISTS idx_calendar_items_pillar ON calendar_items (pillar);
```

---

## Execution Order

| Step | Phase | Dependency | Effort |
|------|-------|------------|--------|
| 1 | Phase 6: DB schema | None | Small |
| 2 | Phase 1: BrandIntelligence | Phase 6 | Medium |
| 3 | Phase 2: Research prompts | None | Medium |
| 4 | Phase 3: Strategy prompts | Phase 2 (persona cross-ref) | Medium |
| 5 | Phase 4: Planning prompts | Phase 1 + 3 (dedup + enriched items) | Medium |
| 6 | Phase 5: Content prompts | Phase 1 (BrandIntelligence) | Large |
| 7 | Phase 7: Token budgets | Phase 5 | Small |
| 8 | Phase 8: Frontend rendering | Phase 2-5 (enriched data) | Medium |

---

## Success Criteria

A single Instagram caption prompt should contain:
- Full brand positioning and voice (not truncated)
- The specific content pillar and why it matters
- The target persona with their pain points and tone preference
- The monthly theme and this week's sub-theme
- Product details with benefits (if product post)
- The strategy document's guidance for this month
- Last 30 days of posted content (to avoid repetition)
- Top 5 performing captions (to learn from success)
- The campaign goals and creative direction
- Brand color palette and visual style
- Explicit CTA with brand URL

**That is what world-class looks like — and GPT-5.4 can handle all of it in a single prompt.**
