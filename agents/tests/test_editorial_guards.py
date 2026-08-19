"""Tests for the deterministic editorial guards (cycle-4, Task B).

Covers the three defect classes the 624-item production calendar exposed:
stale anticipation after an event has passed, statistic/title repetition
across the horizon, and generator meta-language leaking into content briefs.
"""

import asyncio
import json
import os
import sys

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.planning.nodes as planning_nodes
from shared.editorial import (
    VARIETY_RULES_BLOCK,
    apply_temporal_guard,
    build_recent_usage_block,
    build_temporal_block,
    deanticipate_item,
    extract_stats,
    find_anticipatory_markers,
    find_brief_meta_phrases,
    find_referenced_events,
    find_stale_anticipation,
    format_repetition_report,
    item_title,
    normalize_stat,
    repetition_report,
    scrub_anticipatory_language,
    scrub_brief_fields,
    scrub_brief_meta,
    stat_window_violations,
)

# The real Naturespan event shapes: two same-day store openings, a movable
# festival, a plain awareness day, and a multi-day range.
EVENTS = [
    {
        "title": "Grand Baie Store Opening",
        "description": "Opening of the new Naturespan magasin bio in Grand Baie",
        "start": "2026-09-01",
        "end": None,
        "category": "brand_milestone",
    },
    {
        "title": "Tamarin Store Opening",
        "description": "Opening of the second Naturespan shop in Tamarin",
        "start": "2026-09-01",
        "end": None,
        "category": "brand_milestone",
    },
    {
        "title": "Opening Countdown Week",
        "description": "Countdown campaign across all channels",
        "start": "2026-08-23",
        "end": "2026-08-31",
        "category": "campaign",
    },
    {
        "title": "Diwali",
        "description": "Festival of lights",
        "start": "2026-11-08",
        "end": None,
        "category": "holiday",
    },
    {
        "title": "World Food Day",
        "description": "",
        "start": "2026-10-16",
        "end": None,
        "category": "observance",
    },
]


# ── find_anticipatory_markers ────────────────────────────────────────


def test_detects_each_documented_anticipatory_marker():
    cases = {
        "Countdown to the big opening": "countdown",
        "Visit the upcoming magasin bio": "upcoming",
        "Our new shop is opening soon": "opening soon",
        "New range coming soon": "coming soon",
        "J-7 before the doors open": "j-countdown",
        "Get ready for something special": "get ready for",
        "Build anticipation for the launch": "build anticipation",
        "Save the date for our party": "save the date",
        "Only 3 days to go": "days to go",
    }
    for text, expected in cases.items():
        assert expected in find_anticipatory_markers(text), text


def test_neutral_copy_carries_no_markers():
    assert find_anticipatory_markers("Our Grand Baie shop is open every day") == []
    assert find_anticipatory_markers("") == []
    assert find_anticipatory_markers(None) == []


# ── scrub_anticipatory_language ──────────────────────────────────────


def test_scrub_rewrites_countdown_into_celebration_and_keeps_the_subject():
    out, markers = scrub_anticipatory_language("Countdown to the Grand Baie opening")
    assert "countdown" in markers
    assert "countdown" not in out.lower()
    assert "Grand Baie opening" in out
    assert out[0].isupper()


def test_scrub_drops_the_upcoming_but_keeps_the_article_and_the_noun():
    out, _ = scrub_anticipatory_language("Visit the upcoming magasin bio")
    assert out == "Visit the magasin bio"


def test_scrub_repairs_punctuation_left_by_a_removed_j_countdown():
    out, markers = scrub_anticipatory_language("J-7: Get ready for our new magasin bio")
    assert "j-countdown" in markers
    assert not out.startswith(":")
    assert "J-7" not in out
    assert "magasin bio" in out


def test_scrub_is_a_noop_without_markers():
    text = "Our Grand Baie shop is open every day"
    assert scrub_anticipatory_language(text) == (text, [])


def test_scrub_never_blanks_a_field():
    # Every token is anticipatory; the original must survive rather than
    # leaving the calendar item with an empty title.
    out, markers = scrub_anticipatory_language("Upcoming")
    assert markers == ["upcoming"]
    assert out == "Upcoming"


# ── find_referenced_events ───────────────────────────────────────────


def test_event_is_matched_through_its_description_not_just_its_title():
    # The production defect never named "Grand Baie Store Opening" — it said
    # "the upcoming magasin bio", which only the description carries.
    matched = find_referenced_events("Visit the upcoming magasin bio", EVENTS)
    assert [e["title"] for e in matched] == ["Grand Baie Store Opening"]


def test_single_shared_generic_token_does_not_bind_an_event():
    # "new" appears in several event descriptions and identifies none of them.
    assert find_referenced_events("A new week of recipes", EVENTS) == []


def test_single_token_event_title_matches_on_that_token():
    matched = find_referenced_events("Lighting lamps for Diwali", EVENTS)
    assert [e["title"] for e in matched] == ["Diwali"]


def test_unrelated_copy_matches_nothing():
    assert find_referenced_events("Three ways to use moringa powder", EVENTS) == []
    assert find_referenced_events("", EVENTS) == []


# ── find_stale_anticipation (marker + event date context) ────────────


def test_anticipation_before_the_event_is_not_a_defect():
    assert find_stale_anticipation(
        "Countdown to the Grand Baie store opening", "2026-08-25", EVENTS
    ) == []


def test_anticipation_after_the_event_is_flagged_with_the_event_and_date():
    stale = find_stale_anticipation(
        "Visit the upcoming magasin bio", "2026-09-15", EVENTS
    )
    assert len(stale) == 1
    assert stale[0]["event"] == "Grand Baie Store Opening"
    assert stale[0]["event_date"] == "2026-09-01"
    assert stale[0]["scheduled_date"] == "2026-09-15"
    assert "upcoming" in stale[0]["markers"]


def test_anticipation_on_the_event_day_itself_is_allowed():
    # Publishing "coming soon" the morning of is judged in-range, not stale.
    assert find_stale_anticipation(
        "The Grand Baie magasin bio opens soon", "2026-09-01", EVENTS
    ) == []


def test_range_events_are_judged_on_their_end_date():
    # Inside the declared countdown week, countdown framing is correct...
    assert find_stale_anticipation(
        "Countdown week continues at Naturespan", "2026-08-27", EVENTS
    ) == []
    # ...and after it closes, it is not.
    stale = find_stale_anticipation(
        "Countdown week continues at Naturespan", "2026-09-10", EVENTS
    )
    assert [s["event"] for s in stale] == ["Opening Countdown Week"]


def test_markers_without_a_referenced_event_are_left_alone():
    # "Coming soon" about an unlisted thing is not something we can date.
    assert find_stale_anticipation(
        "A new recipe series coming soon", "2026-09-15", EVENTS
    ) == []


def test_unparseable_scheduled_date_is_not_flagged():
    assert find_stale_anticipation("the upcoming magasin bio", "", EVENTS) == []
    assert find_stale_anticipation("the upcoming magasin bio", None, EVENTS) == []


# ── deanticipate_item / apply_temporal_guard ─────────────────────────


def test_deanticipate_item_rewrites_copy_fields_and_reports_what_changed():
    item = {
        "scheduled_date": "2026-09-15",
        "theme": "Countdown to the upcoming magasin bio",
        "content_brief": "Build anticipation for the new magasin bio in Grand Baie.",
        "campaign_name": "Opening Countdown",
    }
    finding = deanticipate_item(item, EVENTS)

    assert finding is not None
    # Both the opening and the countdown week that closed on Aug 31 are stale
    # on Sept 15; campaign_name counts as evidence even though it is not
    # rewritten, which is how "Opening Countdown" is recognised here.
    assert "Grand Baie Store Opening" in finding["events"]
    assert "Opening Countdown Week" in finding["events"]
    assert "countdown" not in item["theme"].lower()
    assert "anticipation" not in item["content_brief"].lower()
    assert set(finding["fields_rewritten"]) == {"theme", "content_brief"}
    # campaign_name is the grouping key across items and is deliberately kept.
    assert item["campaign_name"] == "Opening Countdown"


def test_deanticipate_item_leaves_a_still_future_event_alone():
    """Cross-event false positive: one past event must not scrub every field.

    campaign_name is event-named (routine in this codebase) and its event has
    passed, but the theme counts down to Diwali, which is still ahead on
    publish day. Blanket-rewriting turned correct copy into false copy.
    """
    item = {
        "scheduled_date": "2026-09-15",
        "campaign_name": "Grand Baie Store Opening follow-up",
        "theme": "Countdown to Diwali, the festival of lights",
        "content_brief": "Build anticipation for the new magasin bio in Grand Baie.",
    }
    finding = deanticipate_item(item, EVENTS)

    assert finding is not None
    # Diwali (2026-11-08) is still ahead — its countdown is TRUE on Sept 15.
    assert item["theme"] == "Countdown to Diwali, the festival of lights"
    assert "theme" in finding["fields_kept"]
    # The already-past store opening is still de-anticipated.
    assert "anticipation" not in item["content_brief"].lower()
    assert finding["fields_rewritten"] == ["content_brief"]


def test_deanticipate_item_still_scrubs_when_no_event_is_ahead():
    item = {
        "scheduled_date": "2026-09-15",
        "campaign_name": "Grand Baie Store Opening follow-up",
        "theme": "Countdown to the upcoming magasin bio",
    }
    finding = deanticipate_item(item, EVENTS)

    assert finding is not None
    assert finding["fields_kept"] == []
    assert "countdown" not in item["theme"].lower()


def test_deanticipate_item_returns_none_for_a_clean_item():
    item = {
        "scheduled_date": "2026-09-15",
        "theme": "Our Grand Baie magasin bio is open daily",
    }
    assert deanticipate_item(item, EVENTS) is None
    assert item["theme"] == "Our Grand Baie magasin bio is open daily"


def test_apply_temporal_guard_never_drops_items():
    items = [
        {"scheduled_date": "2026-08-25", "theme": "Countdown to the magasin bio"},
        {"scheduled_date": "2026-09-15", "theme": "The upcoming magasin bio"},
        {"scheduled_date": "2026-09-20", "theme": "Three ways to use moringa"},
    ]
    findings = apply_temporal_guard(items, EVENTS)

    assert len(items) == 3                      # nothing dropped
    assert len(findings) == 1                   # only the post-opening item
    assert findings[0]["scheduled_date"] == "2026-09-15"
    assert items[0]["theme"] == "Countdown to the magasin bio"   # still valid
    assert "upcoming" not in items[1]["theme"].lower()
    assert items[2]["theme"] == "Three ways to use moringa"


def test_apply_temporal_guard_accepts_datetime_scheduled_at():
    from datetime import datetime

    items = [{
        "scheduled_at": datetime(2026, 9, 15, 7, 30),
        "theme": "The upcoming magasin bio",
    }]
    assert len(apply_temporal_guard(items, EVENTS)) == 1


def test_apply_temporal_guard_is_a_noop_without_events():
    items = [{"scheduled_date": "2026-09-15", "theme": "The upcoming magasin bio"}]
    assert apply_temporal_guard(items, []) == []
    assert items[0]["theme"] == "The upcoming magasin bio"


# ── statistics extraction + repetition counters ──────────────────────


def test_normalize_stat_collapses_sign_and_spacing_variants():
    assert normalize_stat("+69 %") == "69%"
    assert normalize_stat("69%") == "69%"
    assert normalize_stat("+ 69%") == "69%"
    assert normalize_stat("1,5 %") == "1.5%"


def test_extract_stats_finds_percentages_multipliers_and_years():
    stats = extract_stats("+69% more antioxidants, 3x the vitamin C, 20+ years on")
    assert "69%" in stats
    assert "3x" in stats
    assert "20+years" in stats


def test_extract_stats_ignores_pack_sizes():
    # Pack weights are not claims; counting them would swamp the report.
    assert extract_stats("Miel de Lavande 500g and 250ml oil") == []


def test_item_title_prefers_theme_then_title_then_campaign():
    assert item_title({"theme": "T", "title": "X"}) == "T"
    assert item_title({"title": "X", "campaign_name": "C"}) == "X"
    assert item_title({"campaign_name": "C"}) == "C"
    assert item_title({}) == ""


def test_repetition_report_counts_repeated_titles_and_stats():
    items = [
        {
            "scheduled_date": f"2026-0{m}-01",
            "theme": "Antioxidant power",
            "content_brief": "Moringa keeps +69% more antioxidants.",
        }
        for m in range(1, 6)
    ] + [
        {
            "scheduled_date": "2026-06-01",
            "theme": "Supplier story",
            "content_brief": "Meet the farm behind the harvest.",
        }
    ]
    report = repetition_report(items)

    assert report["items"] == 6
    assert report["unique_titles"] == 2
    assert report["top_titles"][0] == {"title": "Antioxidant power", "count": 5}
    assert report["top_stats"][0] == {"stat": "69%", "count": 5}


def test_repetition_report_omits_things_used_only_once():
    items = [
        {"scheduled_date": "2026-01-01", "theme": "A", "content_brief": "+69% more"},
        {"scheduled_date": "2026-02-01", "theme": "B", "content_brief": "3x more"},
    ]
    report = repetition_report(items)
    assert report["top_titles"] == []
    assert report["top_stats"] == []
    assert report["stat_window_violations"] == []


def test_repetition_report_handles_an_empty_run():
    report = repetition_report([])
    assert report["items"] == 0
    assert report["unique_titles"] == 0
    assert report["top_stats"] == []
    assert "items=0" in format_repetition_report(report)


# ── rolling 4-week statistic window ──────────────────────────────────


def test_stat_reused_inside_four_weeks_is_a_window_violation():
    items = [
        {"scheduled_date": "2026-01-01", "content_brief": "+69% more antioxidants"},
        {"scheduled_date": "2026-01-20", "content_brief": "+69% more antioxidants"},
    ]
    violations = stat_window_violations(items)
    assert len(violations) == 1
    assert violations[0]["stat"] == "69%"
    assert violations[0]["count"] == 2
    assert violations[0]["window_start"] == "2026-01-01"


def test_stat_respaced_beyond_four_weeks_is_clean():
    items = [
        {"scheduled_date": "2026-01-01", "content_brief": "+69% more antioxidants"},
        {"scheduled_date": "2026-02-15", "content_brief": "+69% more antioxidants"},
    ]
    assert stat_window_violations(items) == []


def test_window_violation_reports_the_worst_window_not_the_first():
    items = (
        [{"scheduled_date": "2026-01-01", "content_brief": "+69%"}]
        + [
            {"scheduled_date": d, "content_brief": "+69%"}
            for d in ("2026-06-01", "2026-06-05", "2026-06-09")
        ]
    )
    violations = stat_window_violations(items)
    assert violations[0]["count"] == 3
    assert violations[0]["window_start"] == "2026-06-01"
    assert violations[0]["total"] == 4


def test_items_without_a_usable_date_are_skipped_not_crashed():
    items = [
        {"content_brief": "+69% more"},
        {"scheduled_date": "nope", "content_brief": "+69% more"},
    ]
    assert stat_window_violations(items) == []


# ── recently-used prompt block ───────────────────────────────────────


def test_recent_usage_block_is_empty_before_anything_was_generated():
    assert build_recent_usage_block([], [], channel="instagram") == ""


def test_recent_usage_block_lists_titles_and_stats_and_names_the_channel():
    block = build_recent_usage_block(
        ["Antioxidant power", "Supplier story"], ["69%"], channel="instagram"
    )
    assert "INSTAGRAM" in block
    assert "Antioxidant power" in block
    assert "Supplier story" in block
    assert "69%" in block


def test_recent_usage_block_dedupes_and_caps():
    block = build_recent_usage_block(
        ["A"] * 10 + [f"T{i}" for i in range(10)], [], max_titles=5
    )
    titles = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(titles) == 5
    assert block.count("- A\n") <= 1


# ── brief hygiene ────────────────────────────────────────────────────


def test_finds_the_documented_meta_phrases():
    brief = (
        "This post should highlight the antioxidant content. "
        "Focus on the harvest. "
        "The caption explains how the leaf is dried."
    )
    found = find_brief_meta_phrases(brief)
    assert "this-post-should" in found
    assert "focus-on" in found
    assert "the-caption-explains" in found


def test_scrub_brief_meta_keeps_the_substance_and_drops_the_commentary():
    out = scrub_brief_meta(
        "This post should highlight the antioxidant content of the moringa powder."
    )
    assert out == "Highlight the antioxidant content of the moringa powder."


def test_scrub_brief_meta_handles_every_sentence_not_just_the_first():
    out = scrub_brief_meta(
        "Moringa is harvested by hand. Focus on the drying racks."
    )
    assert out == "Moringa is harvested by hand. The drying racks."


def test_scrub_brief_meta_leaves_clean_creative_direction_untouched():
    brief = (
        "Moringa leaf powder keeps more antioxidants than the fresh leaf. "
        "Show the scoop against a dark bowl."
    )
    assert scrub_brief_meta(brief) == brief


def test_scrub_brief_meta_never_returns_an_empty_brief():
    # An empty content_brief makes the content workflow refuse the item.
    assert scrub_brief_meta("This post should.") == "This post should."
    assert scrub_brief_meta("") == ""
    assert scrub_brief_meta(None) == ""


def test_scrub_brief_fields_reports_which_fields_it_rewrote():
    item = {
        "content_brief": "Focus on the supplier story.",
        "description": "Meet the farmer who grows our turmeric.",
    }
    assert scrub_brief_fields(item) == ["content_brief"]
    assert item["content_brief"] == "The supplier story."
    assert item["description"] == "Meet the farmer who grows our turmeric."


# ── per-item temporal prompt block (content workflow) ────────────────


def test_temporal_block_splits_past_from_future_on_the_publish_date():
    block = build_temporal_block("2026-09-15", EVENTS)
    past, future = block.split("Still ahead on that day")
    assert "2026-09-15" in block
    assert "Grand Baie Store Opening" in past
    assert "Diwali" in future
    assert "Diwali" not in past


def test_temporal_block_is_empty_without_a_date_or_events():
    assert build_temporal_block(None, EVENTS) == ""
    assert build_temporal_block("2026-09-15", []) == ""


# ── wave sizing + the repetition signal actually reaching batch N+1 ──


def test_wave_size_keeps_the_llm_pool_saturated():
    # windows x channels should be about three semaphore rounds, so waves
    # cost ordering, not throughput — clamped by the variety rule's window.
    for channels in (1, 2, 3, 4, 8):
        size = planning_nodes._wave_size(channels)
        assert size >= 1
        assert size <= planning_nodes._MAX_WAVE_WINDOWS
        if 2 <= channels <= 8:
            assert size * channels >= 8  # at least one full round per wave


def test_wave_never_exceeds_the_variety_rule_it_enforces():
    # Batches inside a wave cannot see each other, so a wave wider than the
    # rule's rolling window makes the rule structurally unenforceable.
    assert planning_nodes._MAX_WAVE_WINDOWS == 4
    assert "rolling 4-week window" in VARIETY_RULES_BLOCK
    for channels in (1, 2, 3, 4, 8):
        assert planning_nodes._wave_size(channels) <= 4


def test_wave_size_survives_degenerate_channel_counts():
    assert planning_nodes._wave_size(0) >= 1
    assert planning_nodes._wave_size(None) >= 1


class _RecordingLLM:
    """Returns one calendar item per call and records every prompt seen."""

    def __init__(self):
        self.prompts = []
        self.calls = 0

    async def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.calls += 1
        # A distinct title per week so wave 2 has something to be told about.
        return json.dumps([{
            "scheduled_date": f"2026-01-{min(28, self.calls):02d}",
            "scheduled_time": "07:00",
            "platform": "instagram",
            "content_type": "post",
            "campaign_name": "C",
            "pillar": "Trust",
            "theme": f"Wave title {self.calls}",
            "weekly_sub_theme": f"Sub {self.calls}",
            "target_audience": "Families",
            "content_brief": "Moringa keeps +69% more antioxidants than the fresh leaf.",
            "visual_direction": "Scoop on dark bowl",
            "cta_type": "learn",
        }])


@pytest.fixture
def calendar_state(monkeypatch):
    async def _get_products(_brand_id):
        return []

    monkeypatch.setattr(planning_nodes, "get_products", _get_products)
    return {
        "brand_id": "b1",
        "campaigns": [{"name": "C"}],
        "strategy": {"cadence": {"instagram": {"posts_per_week": 1}}},
        "strategy_document": "",
        "enabled_channels": ["instagram"],
        "existing_items": [],
        "events": EVENTS,
        "brand_context": "BRAND",
        "scope_weeks": 26,
        "content_format": "posts_only",
    }


def test_later_waves_are_told_what_earlier_waves_already_used(monkeypatch, calendar_state):
    """The whole point of waves — regression guard against a silent no-op.

    With a single flat gather every batch would see an empty "already used"
    block and the damping would do nothing while looking implemented.
    """
    llm = _RecordingLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    asyncio.run(planning_nodes._generate_calendar_inner(calendar_state))

    user_messages = [p[1]["content"] for p in llm.prompts]
    wave_size = planning_nodes._wave_size(1)

    # Nothing had been generated when the first wave was built.
    assert "ALREADY USED EARLIER IN THIS PLAN" not in user_messages[0]
    # ...but batches after the first wave boundary carry the real signal.
    assert len(user_messages) > wave_size, "need more than one wave to test this"
    later = user_messages[wave_size]
    assert "ALREADY USED EARLIER IN THIS PLAN" in later
    assert "Wave title 1" in later
    assert "69%" in later


def test_batch_prompts_carry_the_temporal_variety_and_brief_rules(monkeypatch, calendar_state):
    llm = _RecordingLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    asyncio.run(planning_nodes._generate_calendar_inner(calendar_state))

    system = llm.prompts[0][0]["content"]
    assert "TEMPORAL RULES" in system
    assert "VARIETY RULES" in system
    assert "CONTENT BRIEF STYLE" in system
    assert "rolling 4-week window" in system


def test_generated_calendar_is_scrubbed_before_it_leaves_the_node(monkeypatch, calendar_state):
    class _StaleLLM(_RecordingLLM):
        async def __call__(self, prompt, **kwargs):
            self.calls += 1
            self.prompts.append(prompt)
            return json.dumps([{
                "scheduled_date": "2026-09-15",
                "scheduled_time": "07:00",
                "platform": "instagram",
                "theme": "Countdown to the upcoming magasin bio",
                "content_brief": "This post should build anticipation for the magasin bio.",
            }])

    monkeypatch.setattr(planning_nodes, "chat_completion", _StaleLLM())
    result = asyncio.run(planning_nodes._generate_calendar_inner(calendar_state))

    items = result["calendar_items"]
    assert items, "items must never be dropped by the guards"
    for item in items:
        assert "countdown" not in item["theme"].lower()
        assert "upcoming" not in item["theme"].lower()
        assert not item["content_brief"].lower().startswith("this post should")
        assert "anticipation" not in item["content_brief"].lower()


def test_post_generation_checks_report_repetition_without_failing(caplog):
    items = [
        {
            "scheduled_date": "2026-01-01",
            "theme": "Antioxidant power",
            "content_brief": "Moringa keeps +69% more antioxidants.",
        },
        {
            "scheduled_date": "2026-01-15",
            "theme": "Antioxidant power",
            "content_brief": "Moringa keeps +69% more antioxidants.",
        },
    ]
    report = planning_nodes._apply_post_generation_checks("b1", items, EVENTS)

    assert report["top_titles"][0]["count"] == 2
    assert report["top_stats"][0]["stat"] == "69%"
    assert report["stat_window_violations"][0]["count"] == 2
    assert len(items) == 2  # log-only: nothing rejected
