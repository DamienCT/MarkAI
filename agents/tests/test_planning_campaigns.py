"""Tests for campaign output integrity: chunking, merge, validation gate.

Covers the cycle-2 critical finding — a full year of campaigns generated in
one call, truncated mid-value, then persisted as a single "General Campaign"
record whose description held the raw escaped JSON.
"""

import asyncio
import json
import os
import re
import sys
from datetime import date, timedelta

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.planning.nodes as planning_nodes
from workflows.planning.nodes import (
    CampaignIntegrityError,
    _add_months,
    _campaign_chunk_windows,
    _campaigns_from_prompt,
    _chunk_months,
    _coerce_campaign_list,
    _looks_like_embedded_json,
    _merge_campaign_chunks,
    _min_expected_campaigns,
    _missing_document_months,
    _months_in_window,
    _parse_campaign_date,
    _partition_campaigns,
    _validate_campaigns,
)


def _campaign(name: str, start: str = "2026-09-01", end: str = "2026-09-30", **extra) -> dict:
    base = {
        "name": name,
        "description": f"{name} description, two sentences worth of prose.",
        "start_date": start,
        "end_date": end,
        "pillar": "Trust",
        "platforms": ["instagram"],
        "goal": "awareness",
        "target_audience": "Health-conscious families",
    }
    base.update(extra)
    return base


# ── _add_months ──────────────────────────────────────────────────────


def test_add_months_clamps_to_last_day_of_target_month():
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # leap year
    assert _add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)


def test_add_months_rolls_the_year_over():
    assert _add_months(date(2026, 11, 19), 3) == date(2027, 2, 19)
    assert _add_months(date(2026, 12, 15), 12) == date(2027, 12, 15)


# ── _campaign_chunk_windows ──────────────────────────────────────────


def test_chunk_windows_splits_a_year_into_quarters_and_tiles_it():
    start, end = date(2026, 8, 19), date(2027, 8, 18)
    windows = _campaign_chunk_windows(start, end)

    assert len(windows) == 4
    # Contiguous, no gaps, no overlaps, exactly covering [start, end).
    assert windows[0][0] == start
    assert windows[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start


def test_chunk_windows_never_exceeds_the_horizon():
    windows = _campaign_chunk_windows(date(2026, 8, 19), date(2027, 8, 18))
    assert all(s < e for s, e in windows)
    assert all(e <= date(2027, 8, 18) for _, e in windows)


def test_chunk_windows_collapses_short_horizons_to_one_call():
    # Activation runs a 2-week scope — chunking must not multiply the calls.
    windows = _campaign_chunk_windows(date(2026, 8, 19), date(2026, 9, 2))
    assert windows == [(date(2026, 8, 19), date(2026, 9, 2))]


def test_chunk_windows_honours_a_custom_chunk_size():
    windows = _campaign_chunk_windows(date(2026, 1, 1), date(2027, 1, 1), months_per_chunk=6)
    assert windows == [
        (date(2026, 1, 1), date(2026, 7, 1)),
        (date(2026, 7, 1), date(2027, 1, 1)),
    ]


def test_chunk_windows_degenerate_range_returns_a_single_window():
    assert _campaign_chunk_windows(date(2026, 8, 19), date(2026, 8, 19)) == [
        (date(2026, 8, 19), date(2026, 8, 19))
    ]


# ── _months_in_window / _chunk_months ────────────────────────────────


def test_months_in_window_is_inclusive_on_both_ends():
    assert _months_in_window(date(2026, 8, 19), date(2026, 10, 3)) == [
        "August 2026",
        "September 2026",
        "October 2026",
    ]


def test_months_in_window_spans_a_year_boundary_and_repeats_the_month_name():
    months = _months_in_window(date(2026, 8, 19), date(2027, 8, 17))
    assert months[0] == "August 2026"
    assert months[-1] == "August 2027"
    assert len(months) == 13


def test_months_in_window_always_yields_at_least_the_start_month():
    assert _months_in_window(date(2026, 8, 19), date(2026, 8, 18)) == ["August 2026"]


def test_chunk_months_tiles_without_overlap():
    months = _months_in_window(date(2026, 8, 19), date(2027, 8, 17))
    chunks = _chunk_months(months)
    assert [len(c) for c in chunks] == [3, 3, 3, 3, 1]
    flat = [m for c in chunks for m in c]
    assert flat == months
    assert len(set(flat)) == len(flat)  # no month written twice


# ── _coerce_campaign_list: the no-raw-string-fallback rule ───────────


def test_coerce_returns_none_for_a_raw_string_so_it_is_never_a_campaign():
    # This is the production bug: the raw (truncated) LLM string used to be
    # wrapped as {"name": "General Campaign", "description": <raw>}.
    assert _coerce_campaign_list(None) is None
    assert _coerce_campaign_list('{"campaigns": [{"name": "Spring Refresh"') is None
    assert _coerce_campaign_list(42) is None


def test_coerce_unwraps_the_json_object_wrapper():
    assert _coerce_campaign_list({"campaigns": [{"name": "A"}, {"name": "B"}]}) == [
        {"name": "A"},
        {"name": "B"},
    ]


def test_coerce_collects_dict_values_when_the_model_keys_each_campaign():
    coerced = _coerce_campaign_list({"campaign_1": {"name": "A"}, "campaign_2": {"name": "B"}})
    assert coerced == [{"name": "A"}, {"name": "B"}]


def test_coerce_drops_non_dict_list_entries_but_keeps_the_list():
    assert _coerce_campaign_list([{"name": "A"}, "junk", 7]) == [{"name": "A"}]


def test_coerce_empty_list_is_a_valid_parse_not_a_parse_failure():
    assert _coerce_campaign_list([]) == []
    assert _coerce_campaign_list({"campaigns": []}) == []


# ── _merge_campaign_chunks ───────────────────────────────────────────


def test_merge_flattens_chunks_in_chronological_order():
    merged = _merge_campaign_chunks(
        [
            [_campaign("Q2", "2027-05-01"), _campaign("Q2b", "2027-06-01")],
            [_campaign("Q1", "2026-09-01")],
        ]
    )
    assert [c["name"] for c in merged] == ["Q1", "Q2", "Q2b"]


def test_merge_drops_boundary_duplicates_keeping_the_first():
    first = _campaign("Back to School", "2026-09-01")
    dupe = _campaign("back to SCHOOL", "2026-09-05", pillar="Other")
    merged = _merge_campaign_chunks([[first], [dupe]])
    assert len(merged) == 1
    assert merged[0]["pillar"] == "Trust"  # first occurrence won


def test_merge_keeps_undated_campaigns_and_sorts_them_last():
    merged = _merge_campaign_chunks(
        [[_campaign("Dated", "2026-09-01")], [_campaign("Undated", start="")]]
    )
    assert [c["name"] for c in merged] == ["Dated", "Undated"]


def test_merge_ignores_non_dict_entries_and_empty_chunks():
    merged = _merge_campaign_chunks([[], [_campaign("Only")], ["junk"]])
    assert [c["name"] for c in merged] == ["Only"]


# ── _min_expected_campaigns ──────────────────────────────────────────


def test_min_expected_scales_with_the_horizon():
    assert _min_expected_campaigns(52) == 6  # ~12 months → at least 6
    assert _min_expected_campaigns(26) == 3
    assert _min_expected_campaigns(4) == 1
    assert _min_expected_campaigns(2) == 1


def test_min_expected_never_drops_below_one_on_junk_input():
    assert _min_expected_campaigns(0) == 1
    assert _min_expected_campaigns(None) == 1
    assert _min_expected_campaigns("nonsense") == 1


# ── _looks_like_embedded_json / _parse_campaign_date ─────────────────


def test_embedded_json_blob_is_detected():
    blob = '[{"name": "Spring Refresh", "description": "' + "x" * 200 + '"}'
    assert _looks_like_embedded_json(blob) is True
    assert _looks_like_embedded_json('{"campaigns": ' + "y" * 200) is True


def test_escaped_campaign_keys_are_detected():
    # The production artifact stored the array ESCAPED inside a description.
    blob = '[{\\"name\\": \\"Spring Refresh\\", \\"start_date\\": \\"2027-03-01\\"' + "x" * 200
    assert _looks_like_embedded_json(blob) is True


def test_ordinary_prose_and_short_values_are_not_flagged():
    assert _looks_like_embedded_json("A warm autumn campaign about family meals.") is False
    assert _looks_like_embedded_json("{short}") is False
    assert _looks_like_embedded_json(None) is False
    assert _looks_like_embedded_json(["a"]) is False


def test_bracket_tagged_prose_is_not_an_embedded_blob():
    """A leading bracket is NOT evidence — this shape cost a brand its whole plan.

    Bracket-tagged descriptions are a normal LLM output shape; flagging them
    raised CampaignIntegrityError, which routes the graph to END with no
    campaigns, no strategy document and no calendar at all.
    """
    prose = (
        "[Launch] Celebrate the opening of our Curepipe store with a two-week "
        "arc of behind-the-scenes reels, supplier stories and a first-week "
        "offer for members."
    )
    assert len(prose) >= 120
    assert _looks_like_embedded_json(prose) is False
    assert (
        _looks_like_embedded_json(
            "{Seasonal} A December arc across gifting, family tables and the "
            "quiet week between the holidays — one supplier story per week and "
            "a closing thank-you note to members."
        )
        is False
    )


def test_parse_campaign_date_accepts_iso_dates_and_timestamps():
    assert _parse_campaign_date("2026-09-01") == date(2026, 9, 1)
    assert _parse_campaign_date("2026-09-01T08:30:00") == date(2026, 9, 1)
    assert _parse_campaign_date(date(2026, 9, 1)) == date(2026, 9, 1)


def test_parse_campaign_date_rejects_prose_and_empty_values():
    assert _parse_campaign_date("early September") is None
    assert _parse_campaign_date("2026-13-45") is None
    assert _parse_campaign_date("") is None
    assert _parse_campaign_date(None) is None


WINDOW = {"window_start": date(2026, 8, 19), "window_end": date(2027, 8, 18)}


# ── _partition_campaigns: the availability gate ──────────────────────


def test_partition_keeps_well_formed_campaigns_untouched():
    campaigns = [_campaign(f"C{i}") for i in range(3)]
    kept, reasons = _partition_campaigns(campaigns)
    assert kept == campaigns
    assert reasons == []


def test_partition_drops_one_defective_campaign_and_keeps_the_rest():
    """One missing end_date on 1 of 8 must not cost the brand its year plan."""
    campaigns = [_campaign(f"C{i}", f"2026-{4 + i:02d}-01", f"2026-{4 + i:02d}-28") for i in range(8)]
    del campaigns[3]["end_date"]

    kept, reasons = _partition_campaigns(campaigns)

    assert len(kept) == 7
    assert "C3" not in {c["name"] for c in kept}
    assert len(reasons) == 1
    assert "missing required field" in reasons[0] and "end_date" in reasons[0]
    # What survives clears the fail-closed gate.
    problems, _ = _validate_campaigns(kept, min_expected=6, **WINDOW)
    assert problems == []


def test_partition_drops_unparseable_and_reversed_dates():
    kept, reasons = _partition_campaigns(
        [
            _campaign("Fuzzy", start="early September"),
            _campaign("Backwards", "2026-10-01", "2026-09-01"),
            _campaign("Good"),
        ]
    )
    assert [c["name"] for c in kept] == ["Good"]
    assert any("unparseable start_date" in r for r in reasons)
    assert any("precedes start_date" in r for r in reasons)


def test_partition_drops_non_dict_entries():
    kept, reasons = _partition_campaigns([_campaign("Fine"), "raw string", None])
    assert [c["name"] for c in kept] == ["Fine"]
    assert len(reasons) == 2


def test_partition_reports_a_non_list_payload():
    kept, reasons = _partition_campaigns({"campaigns": []})
    assert kept == []
    assert reasons and "expected a list" in reasons[0]


def test_partition_never_rescues_a_corrupt_blob():
    # An embedded-JSON description parses and dates fine — partition keeps it
    # so the fail-closed gate can still reject the payload.
    corrupt = _campaign(
        "General Campaign",
        description='[{"name": "Spring Refresh", "start_date": "2027-03-01", "desc'
        + "x" * 400,
    )
    kept, reasons = _partition_campaigns([corrupt])
    assert kept == [corrupt] and reasons == []
    problems, _ = _validate_campaigns(kept, min_expected=1, **WINDOW)
    assert any("embedded JSON blob" in p for p in problems)


# ── _validate_campaigns: the gate ────────────────────────────────────


def test_gate_passes_a_well_formed_set():
    campaigns = [_campaign(f"C{i}", f"2026-{9 + i:02d}-01", f"2026-{9 + i:02d}-28") for i in range(3)]
    problems, per_month = _validate_campaigns(campaigns, min_expected=3, **WINDOW)
    assert problems == []
    assert per_month == {"2026-09": 1, "2026-10": 1, "2026-11": 1}


def test_gate_reports_missing_required_fields():
    bad = _campaign("No End")
    del bad["end_date"]
    problems, _ = _validate_campaigns([bad], min_expected=1, **WINDOW)
    assert any("missing required field" in p and "end_date" in p for p in problems)


def test_gate_treats_a_blank_required_field_as_missing():
    problems, _ = _validate_campaigns([_campaign("Blank", start="  ")], min_expected=1, **WINDOW)
    assert any("missing required field" in p and "start_date" in p for p in problems)
    # Not double-reported as unparseable.
    assert not any("unparseable start_date" in p for p in problems)


def test_gate_reports_an_unparseable_date():
    problems, _ = _validate_campaigns(
        [_campaign("Fuzzy", start="early September")], min_expected=1, **WINDOW
    )
    assert any("unparseable start_date" in p for p in problems)


def test_gate_reports_reversed_dates():
    problems, _ = _validate_campaigns(
        [_campaign("Backwards", "2026-10-01", "2026-09-01")], min_expected=1, **WINDOW
    )
    assert any("precedes start_date" in p for p in problems)


def test_gate_reports_too_few_campaigns_for_the_scope():
    problems, _ = _validate_campaigns([_campaign("Lonely")], min_expected=6, **WINDOW)
    assert any("expected at least 6" in p for p in problems)


def test_gate_rejects_the_production_corruption_shape():
    # One record whose description holds the whole (truncated) campaign array.
    corrupt = {
        "name": "General Campaign",
        "description": '[{"name": "Spring Refresh", "start_date": "2027-03-01", "desc'
        + "x" * 400,
        "start_date": "2026-08-19",
        "end_date": "2027-08-18",
    }
    problems, _ = _validate_campaigns([corrupt], min_expected=1, **WINDOW)
    assert any("embedded JSON blob" in p for p in problems)


def test_gate_rejects_a_non_list_payload():
    problems, per_month = _validate_campaigns({"campaigns": []}, min_expected=1, **WINDOW)
    assert problems and "expected a list" in problems[0]
    assert per_month == {}


def test_gate_rejects_non_dict_entries():
    problems, _ = _validate_campaigns([_campaign("Fine"), "raw string"], min_expected=1, **WINDOW)
    assert any("expected an object" in p for p in problems)


def test_gate_rejects_a_payload_that_cannot_be_serialized():
    problems, _ = _validate_campaigns(
        [_campaign("Bad", start=date(2026, 9, 1))], min_expected=1, **WINDOW
    )
    assert any("not JSON-serializable" in p for p in problems)


def test_gate_output_round_trips_when_it_passes():
    campaigns = [_campaign(f"C{i}") for i in range(2)]
    problems, _ = _validate_campaigns(campaigns, min_expected=1, **WINDOW)
    assert problems == []
    assert json.loads(json.dumps(campaigns)) == campaigns


def test_gate_counts_campaigns_per_month_for_the_log_summary():
    campaigns = [
        _campaign("A", "2026-09-01"),
        _campaign("B", "2026-09-20"),
        _campaign("C", "2026-11-01"),
    ]
    _, per_month = _validate_campaigns(campaigns, min_expected=1, **WINDOW)
    assert per_month == {"2026-09": 2, "2026-11": 1}


def test_gate_only_warns_when_a_campaign_falls_outside_the_window():
    problems, _ = _validate_campaigns(
        [_campaign("Early Bird", "2025-01-01", "2025-01-31")], min_expected=1, **WINDOW
    )
    assert problems == []


# ── _missing_document_months ─────────────────────────────────────────


DOC = """# Content Calendar Strategy

## Yearly Overview

| Month | Theme |
| September 2026 | Harvest |
| October 2026 | Wellness |

## Q1 Strategy

### September 2026
- theme

### October 2026
- theme
"""


def test_missing_months_counts_only_header_sections_not_table_rows():
    assert _missing_document_months(DOC, ["September 2026", "October 2026"]) == []
    # November appears nowhere at all.
    assert _missing_document_months(DOC, ["November 2026"]) == ["November 2026"]


def test_missing_months_distinguishes_the_same_month_in_different_years():
    doc = "### August 2026\n- theme\n"
    assert _missing_document_months(doc, ["August 2026"]) == []
    assert _missing_document_months(doc, ["August 2027"]) == ["August 2027"]


def test_missing_months_accepts_a_yearless_header():
    doc = "### August\n- theme\n"
    assert _missing_document_months(doc, ["August 2026"]) == []


def test_a_yearless_header_covers_only_one_of_two_same_named_months():
    # A 52-week horizon spans 13 months — one "### August" is evidence of ONE
    # August section, not both.
    doc = "### August\n- theme\n"
    assert _missing_document_months(doc, ["August 2026", "August 2027"]) == [
        "August 2027"
    ]


def test_a_dated_header_is_not_stolen_by_an_earlier_yearless_one():
    doc = "### August\n- theme\n\n### August 2027\n- theme\n"
    assert _missing_document_months(doc, ["August 2026", "August 2027"]) == []


def test_missing_months_reports_everything_for_an_empty_document():
    assert _missing_document_months("", ["August 2026", "September 2026"]) == [
        "August 2026",
        "September 2026",
    ]


# ── _campaigns_from_prompt: repair retry + loud failure ──────────────


class _FakeLLM:
    """Stand-in for chat_completion returning canned responses in order."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.responses.pop(0) if self.responses else ""


@pytest.fixture
def patched_llm(monkeypatch):
    def _install(*responses: str) -> _FakeLLM:
        fake = _FakeLLM(*responses)
        monkeypatch.setattr(planning_nodes, "chat_completion", fake)
        return fake

    return _install


PROMPT = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def test_valid_json_needs_no_repair_call(patched_llm):
    fake = patched_llm('{"campaigns": [{"name": "Harvest"}]}')
    result = asyncio.run(_campaigns_from_prompt(PROMPT, label="w1"))
    assert result == [{"name": "Harvest"}]
    assert len(fake.calls) == 1


def test_campaign_calls_are_capped_well_below_a_year_of_output(patched_llm):
    fake = patched_llm('{"campaigns": []}')
    asyncio.run(_campaigns_from_prompt(PROMPT, label="w1"))
    assert fake.calls[0]["max_tokens"] == planning_nodes._CAMPAIGN_MAX_TOKENS
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_truncated_json_triggers_one_repair_retry_that_recovers(patched_llm):
    truncated = '{"campaigns": [{"name": "Harvest", "description": "abc'
    fake = patched_llm(truncated, '{"campaigns": [{"name": "Harvest"}]}')
    result = asyncio.run(_campaigns_from_prompt(PROMPT, label="w1"))
    assert result == [{"name": "Harvest"}]
    assert len(fake.calls) == 2
    # The repair pass is deterministic and sees the broken text.
    assert fake.calls[1]["temperature"] == 0.0
    assert truncated[:40] in fake.calls[1]["messages"][1]["content"]


def test_unparseable_after_repair_fails_loudly_and_never_wraps_the_raw_string(patched_llm):
    truncated = '{"campaigns": [{"name": "Harvest", "description": "abc'
    fake = patched_llm(truncated, "still not json at all")
    with pytest.raises(CampaignIntegrityError) as exc:
        asyncio.run(_campaigns_from_prompt(PROMPT, label="campaigns[2026-08-19..2026-11-19]"))
    assert "refusing to persist raw LLM output" in str(exc.value)
    assert "campaigns[2026-08-19..2026-11-19]" in str(exc.value)
    assert len(fake.calls) == 2


def test_no_raw_string_ever_becomes_a_campaign_record(patched_llm):
    """Regression guard for the 'General Campaign' fallback."""
    patched_llm("totally invalid", "still invalid")
    with pytest.raises(CampaignIntegrityError):
        asyncio.run(_campaigns_from_prompt(PROMPT, label="w1"))


def test_repair_result_is_still_gated_by_validation(patched_llm):
    # A repair that returns a lone "General Campaign" wrapper is still caught
    # downstream by the validation gate, not silently persisted.
    blob = '[{"name": "Spring", "start_date": "2027-03-01"' + "z" * 300
    patched_llm("broken", json.dumps({"campaigns": [{"name": "General Campaign", "description": blob}]}))
    recovered = asyncio.run(_campaigns_from_prompt(PROMPT, label="w1"))
    problems, _ = _validate_campaigns(recovered, min_expected=1, **WINDOW)
    assert any("embedded JSON blob" in p for p in problems)


# ── _generate_campaigns_inner: end-to-end wiring ─────────────────────


_WINDOW_RE = re.compile(r"ONLY for (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})")
_MONTHS_RE = re.compile(r"Months to cover, in order: (.+)")


class _ScriptedLLM:
    """Responds based on which prompt it is handed, like the real proxy would.

    Campaign calls get campaigns dated inside the window they were asked for;
    strategy-document calls get markdown headers for the months they were
    asked for. Records every call for assertions.
    """

    def __init__(self, campaigns_per_window: int = 2, drop_months: set | None = None):
        self.campaigns_per_window = campaigns_per_window
        self.drop_months = drop_months or set()
        self.campaign_calls: list[tuple[str, str]] = []
        self.doc_calls: list[list[str]] = []

    async def __call__(self, messages, **kwargs):
        system = messages[0]["content"]
        user = messages[1]["content"]
        # The repair prompt also mentions "campaign planner"; no test using
        # this fake expects one, so surface it instead of silently answering.
        assert "You repair malformed JSON" not in system, "unexpected repair call"
        if "campaign planner" in system:
            match = _WINDOW_RE.search(system)
            start = match.group(1) if match else "2026-08-19"
            end = match.group(2) if match else "2027-08-18"
            self.campaign_calls.append((start, end))
            return json.dumps(
                {
                    "campaigns": [
                        _campaign(f"{start} #{i}", start, end)
                        for i in range(self.campaigns_per_window)
                    ]
                }
            )
        months = [m.strip() for m in _MONTHS_RE.search(user).group(1).split(",")]
        self.doc_calls.append(months)
        if "Yearly Overview" in system:
            return "Executive summary.\n\n## Yearly Overview\n\n| Month | Theme |\n"
        body = "\n".join(
            f"### {m}\n- theme\n" for m in months if m not in self.drop_months
        )
        return f"## Q Strategy\n\n{body}\n---\n"


@pytest.fixture
def planning_state(monkeypatch):
    async def _get_brand(_brand_id):
        return {"name": "Naturespan"}

    async def _get_products(_brand_id):
        return [{"name": "Miel de Lavande", "category": "food"}]

    monkeypatch.setattr(planning_nodes, "get_brand", _get_brand)
    monkeypatch.setattr(planning_nodes, "get_products", _get_products)
    return {
        "brand_id": "brand-1",
        "scope_weeks": 52,
        "enabled_channels": ["instagram", "facebook"],
        "strategy": {"pillars": [{"name": "Trust"}]},
        "events": [],
        "brand_context": "BRAND CONTEXT",
    }


def test_full_year_is_generated_in_quarterly_chunks(monkeypatch, planning_state):
    llm = _ScriptedLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    result = asyncio.run(planning_nodes._generate_campaigns_inner(planning_state))

    # Four campaign windows, tiling the horizon without gaps. The windows are
    # half-open internally but rendered INCLUSIVE in the prompt, so window N
    # ends on the day BEFORE window N+1 starts — no boundary day is claimed
    # by two consecutive windows.
    assert len(llm.campaign_calls) == 4
    ordered = sorted(llm.campaign_calls)
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:]):
        assert date.fromisoformat(prev_end) + timedelta(days=1) == date.fromisoformat(
            next_start
        )
    # Merged, not collapsed into one record.
    assert len(result["campaigns"]) == 8
    assert all(isinstance(c, dict) and c["name"] for c in result["campaigns"])
    assert json.loads(json.dumps(result["campaigns"])) == result["campaigns"]


def test_no_general_campaign_record_survives(monkeypatch, planning_state):
    monkeypatch.setattr(planning_nodes, "chat_completion", _ScriptedLLM())
    result = asyncio.run(planning_nodes._generate_campaigns_inner(planning_state))
    names = {c["name"] for c in result["campaigns"]}
    assert "General Campaign" not in names
    for campaign in result["campaigns"]:
        assert not _looks_like_embedded_json(campaign.get("description"))


def test_strategy_document_covers_every_month_of_the_horizon(monkeypatch, planning_state):
    llm = _ScriptedLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    result = asyncio.run(planning_nodes._generate_campaigns_inner(planning_state))

    covered = [m for chunk in llm.doc_calls[1:] for m in chunk]
    assert len(covered) == len(set(covered))  # each month written exactly once
    assert _missing_document_months(result["strategy_document"], covered) == []
    # Header section + one section per month chunk.
    assert len(llm.doc_calls) == 1 + len(_chunk_months(covered))


def test_too_few_campaigns_fails_the_node_loudly(monkeypatch, planning_state):
    monkeypatch.setattr(planning_nodes, "chat_completion", _ScriptedLLM(campaigns_per_window=0))

    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out["status"] == "failed"
    assert any("campaign validation failed" in e for e in out["errors"])
    assert "campaigns" not in out  # nothing corrupt handed to storage


def _horizon_months(scope_weeks: int = 52) -> list[str]:
    """The months a run started now would be asked to cover."""
    start = planning_nodes.datetime.now(planning_nodes.timezone.utc).date()
    end = start + planning_nodes.timedelta(weeks=scope_weeks) - planning_nodes.timedelta(days=1)
    return _months_in_window(start, end)


def test_a_gutted_strategy_document_fails_the_node(monkeypatch, planning_state):
    # Every monthly section lost to truncation — the exact failure mode a
    # 16K-token single-shot document hit at the tail of the year.
    llm = _ScriptedLLM(drop_months=set(_horizon_months()))
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out["status"] == "failed"
    assert any("strategy document incomplete" in e for e in out["errors"])
    assert "strategy_document" not in out


def test_a_single_missing_month_only_warns(monkeypatch, planning_state):
    horizon_months = _horizon_months()
    llm = _ScriptedLLM(drop_months={horizon_months[-1]})
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out.get("status") != "failed"
    assert _missing_document_months(out["strategy_document"], horizon_months) == [
        horizon_months[-1]
    ]


def test_two_missing_months_fail_the_node(monkeypatch, planning_state):
    """Chunking means one call per quarter — a lost section is a real gap.

    The old threshold (> half the horizon) let 6 of 13 months vanish behind a
    log line, which is exactly the defect the chunking was added to fix.
    """
    horizon_months = _horizon_months()
    llm = _ScriptedLLM(drop_months=set(horizon_months[-2:]))
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out["status"] == "failed"
    assert any("strategy document incomplete" in e for e in out["errors"])


def test_one_defective_campaign_does_not_cost_the_brand_its_plan(
    monkeypatch, planning_state
):
    """The availability gate: drop the entry, keep campaigns + document.

    Previously a single missing end_date raised CampaignIntegrityError, the
    node returned status=failed, the graph routed to END, and the brand got
    no campaigns, no strategy document and no calendar at all.
    """

    class _OneDefectiveCampaign(_ScriptedLLM):
        async def __call__(self, messages, **kwargs):
            raw = await super().__call__(messages, **kwargs)
            if "campaign planner" not in messages[0]["content"]:
                return raw
            payload = json.loads(raw)
            if self.campaign_calls and len(self.campaign_calls) == 2:
                del payload["campaigns"][0]["end_date"]
            return json.dumps(payload)

    llm = _OneDefectiveCampaign()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)

    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out.get("status") != "failed"
    assert len(out["campaigns"]) == 7  # 8 generated, 1 dropped
    assert all(c.get("end_date") for c in out["campaigns"])
    assert out["strategy_document"]


def test_removed_campaigns_are_dropped_after_the_merge(monkeypatch, planning_state):
    llm = _ScriptedLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)
    state = dict(planning_state, scope_weeks=8)

    baseline = asyncio.run(planning_nodes._generate_campaigns_inner(state))
    doomed = baseline["campaigns"][0]["name"]

    state["removed_campaigns"] = [doomed.upper()]
    result = asyncio.run(planning_nodes._generate_campaigns_inner(state))

    assert doomed not in {c["name"] for c in result["campaigns"]}


def test_short_activation_scope_uses_a_single_campaign_call(monkeypatch, planning_state):
    llm = _ScriptedLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)
    asyncio.run(planning_nodes._generate_campaigns_inner(dict(planning_state, scope_weeks=2)))
    assert len(llm.campaign_calls) == 1


def test_one_failing_window_fails_the_whole_node(monkeypatch, planning_state):
    """A window that never returns parseable JSON must not be silently skipped."""
    horizon_start = planning_nodes.datetime.now(planning_nodes.timezone.utc).date()
    windows = _campaign_chunk_windows(
        horizon_start, horizon_start + planning_nodes.timedelta(weeks=52)
    )
    doomed_start = windows[1][0].isoformat()
    good = _ScriptedLLM()

    async def _one_bad_window(messages, **kwargs):
        system = messages[0]["content"]
        if "You repair malformed JSON" in system:
            return "the repair pass failed too"
        match = _WINDOW_RE.search(system)
        if match and match.group(1) == doomed_start:
            return "not json, not even close"
        return await good(messages, **kwargs)

    monkeypatch.setattr(planning_nodes, "chat_completion", _one_bad_window)
    out = asyncio.run(planning_nodes.generate_campaigns(planning_state))

    assert out["status"] == "failed"
    assert any("refusing to persist raw LLM output" in e for e in out["errors"])
    assert doomed_start in out["errors"][-1]
    assert "campaigns" not in out
    # The surviving windows produced campaigns — they are discarded, not stored.
    assert len(good.campaign_calls) == len(windows) - 1


def test_campaigns_are_never_generated_in_a_single_year_long_call(monkeypatch, planning_state):
    """Regression guard for the truncation root cause."""
    llm = _ScriptedLLM()
    monkeypatch.setattr(planning_nodes, "chat_completion", llm)
    asyncio.run(planning_nodes._generate_campaigns_inner(planning_state))

    assert len(llm.campaign_calls) > 1
    for start, end in llm.campaign_calls:
        span_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        assert span_days <= 95  # a quarter at most, never a year
