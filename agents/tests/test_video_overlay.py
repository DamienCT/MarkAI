"""Tests for the burned-in overlay text pass — ASS builder (timing windows,
escaping, hex color conversion, wrap/clamp), the proportional single-shot
distribution, the burn command, and the burn stage's failure/success paths
with ffmpeg fully mocked."""

import asyncio
import os
import subprocess
import sys

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.video.nodes as video_nodes
from workflows.video.nodes import (
    _CTA_FONT_SIZE,
    _OVERLAY_FONT_SIZE,
    _OVERLAY_WRAP_CHARS,
)
from workflows.video.nodes import (
    MAX_OVERLAY_WORDS,
    TARGET_TOTAL_S,
    _OVERLAY_MAX_CHARS,
    _OVERLAY_MIN_ON_SCREEN_S,
    _ass_escape,
    _brand_accent_hex,
    _build_overlay_ass,
    _burn_cmd,
    _burn_overlays,
    _clean_overlay_text,
    _distribute_durations,
    _filter_path,
    _format_ass_time,
    _hex_to_ass_color,
    _normalize_shot_plan,
    _overlay_events,
    _wrap_overlay_text,
)


def _overlay_shots(texts, duration=5.0):
    return [
        {
            "index": i + 1,
            "duration_s": duration,
            "scene": f"SCENE CONTEXT: beat {i + 1}",
            "overlay_text": t,
        }
        for i, t in enumerate(texts)
    ]


class TestHexToAssColor:
    def test_rrggbb_becomes_bbggrr(self):
        assert _hex_to_ass_color("#f59e0b") == "&H0B9EF5&"

    def test_hash_optional_and_case_insensitive(self):
        assert _hex_to_ass_color("F59E0B") == "&H0B9EF5&"

    def test_white_and_pure_channels(self):
        assert _hex_to_ass_color("#ffffff") == "&HFFFFFF&"
        assert _hex_to_ass_color("#ff0000") == "&H0000FF&"
        assert _hex_to_ass_color("#0000ff") == "&HFF0000&"

    def test_invalid_returns_none(self):
        for bad in ("", None, "#fff", "#gggggg", "red", "#f59e0b0"):
            assert _hex_to_ass_color(bad) is None


class TestAssEscape:
    def test_braces_and_backslash_neutralized(self):
        out = _ass_escape("Buy {now} 50\\ off")
        assert "{" not in out and "}" not in out
        assert "\\" not in out

    def test_newlines_collapse_to_spaces(self):
        assert _ass_escape("two\nlines\r\nhere") == "two lines here"

    def test_none_and_empty(self):
        assert _ass_escape(None) == ""
        assert _ass_escape("   ") == ""


class TestWrapOverlayText:
    def test_short_line_stays_single(self):
        assert _wrap_overlay_text("Fresh drop") == "Fresh drop"

    def test_wraps_across_two_lines(self):
        out = _wrap_overlay_text("Slow mornings start with hazelnut")
        lines = out.split("\\N")
        assert 1 < len(lines) <= 2
        assert all(len(line) <= _OVERLAY_WRAP_CHARS for line in lines)

    def test_overflow_beyond_two_lines_is_dropped(self):
        out = _wrap_overlay_text(
            "wordone wordtwo wordthree wordfour wordfive wordsix wordseven"
        )
        lines = out.split("\\N")
        assert len(lines) == 2
        assert all(len(line) <= _OVERLAY_WRAP_CHARS for line in lines)

    def test_giant_word_is_truncated_not_overflowed(self):
        out = _wrap_overlay_text("supercalifragilisticexpialidocious")
        assert len(out) <= _OVERLAY_WRAP_CHARS

    def test_dropped_words_are_logged_as_a_warning(self, caplog):
        # Losing the tail of an on-screen line is a visible content defect —
        # QA must see it in the logs, not have it silently trimmed.
        with caplog.at_level("WARNING", logger=video_nodes.logger.name):
            _wrap_overlay_text(
                "wordone wordtwo wordthree wordfour wordfive wordsix"
            )
        assert any("wordfive" in r.getMessage() for r in caplog.records)

    def test_fitting_text_logs_nothing(self, caplog):
        with caplog.at_level("WARNING", logger=video_nodes.logger.name):
            _wrap_overlay_text("Fresh drop today")
        assert caplog.records == []


class TestFormatAssTime:
    def test_zero(self):
        assert _format_ass_time(0) == "0:00:00.00"

    def test_minutes_and_centiseconds(self):
        assert _format_ass_time(83.456) == "0:01:23.46"

    def test_negative_clamps_to_zero(self):
        assert _format_ass_time(-3) == "0:00:00.00"


class TestCleanOverlayText:
    def test_absent_defaults_to_empty(self):
        assert _clean_overlay_text(None) == ""
        assert _clean_overlay_text("") == ""

    def test_newlines_stripped(self):
        assert _clean_overlay_text("one\ntwo\nthree") == "one two three"

    def test_word_clamp(self):
        out = _clean_overlay_text("a b c d e f g h")
        assert len(out.split()) == MAX_OVERLAY_WORDS

    def test_char_clamp_to_the_two_line_box(self):
        # 6 words that would overflow the 2x18-char box: the tail is dropped
        # HERE (whole words) instead of silently at burn time.
        out = _clean_overlay_text(
            "Slow mornings start with hazelnut coldbrew"
        )
        assert len(out) <= _OVERLAY_MAX_CHARS
        assert out == " ".join("Slow mornings start with hazelnut coldbrew".split()[: len(out.split())])
        assert out.startswith("Slow mornings start")

    def test_char_clamp_never_slices_mid_word(self):
        out = _clean_overlay_text("aaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbb cccccccc")
        assert all(len(w) == 16 for w in out.split())
        assert "cccccccc" not in out

    def test_single_oversized_word_survives_truncated(self):
        # One word longer than the whole box: keep a one-line truncation
        # rather than clamping the line away to ''.
        out = _clean_overlay_text("supercalifragilisticexpialidociousness")
        assert out == "supercalifragilisticexpialidociousness"[:_OVERLAY_WRAP_CHARS]

    def test_normalize_shot_plan_carries_overlay_text(self):
        plan = {
            "hook_line": "Hook",
            "shots": [
                {
                    "index": 1,
                    "duration_s": 3,
                    "scene": "SCENE CONTEXT: open",
                    "overlay_text": "Craving\nsomething  real?",
                },
                {"index": 2, "duration_s": 3, "scene": "SCENE CONTEXT: mid"},
            ],
            "caption": "cap",
            "hashtags": [],
            "cta": "Shop now",
        }
        normalized = _normalize_shot_plan(plan)
        assert normalized["shots"][0]["overlay_text"] == "Craving something real?"
        # Old plans without the field still work — default ''
        assert normalized["shots"][1]["overlay_text"] == ""

    def test_the_hook_is_clamped_to_the_hook_budget_not_the_overlay_one(self):
        # A finished master burned "Certified / organic starts": the plan
        # cleaned the hook against the 20-char Overlay wrap while the burn
        # wrapped it at the Hook style's 16 — "here" vanished at render time.
        # The plan must clamp shot 1 with the SAME budget the burn will use.
        from workflows.video.nodes import (
            _HOOK_WRAP_CHARS,
            _STYLE_LAYOUT,
            _wrap_overlay_text,
        )

        plan = {
            "hook_line": "Hook",
            "shots": [
                {
                    "index": 1,
                    "duration_s": 3,
                    "scene": "SCENE CONTEXT: open",
                    "overlay_text": "Certified organic starts here",
                },
                {
                    "index": 2,
                    "duration_s": 3,
                    "scene": "SCENE CONTEXT: mid",
                    # A mid overlay keeps the roomier Overlay budget.
                    "overlay_text": "Certified organic starts here",
                },
            ],
            "caption": "cap",
            "hashtags": [],
            "cta": "Shop now",
        }
        normalized = _normalize_shot_plan(plan)
        hook = normalized["shots"][0]["overlay_text"]
        # What the plan stores is exactly what the Hook-style burn shows.
        assert _wrap_overlay_text(hook, _HOOK_WRAP_CHARS).replace("\\N", " ") == hook
        assert hook == "Certified organic starts"
        assert normalized["shots"][1]["overlay_text"] == "Certified organic starts here"
        # The burn side reads its wrap from the same constant.
        assert _STYLE_LAYOUT["Hook"][1] == _HOOK_WRAP_CHARS
        # And the trim is REPORTED, so plan_shots can ask for copy that fits
        # instead of shipping the stump.
        assert normalized["hook_trimmed"] is True


class TestHookRewrite:
    """The trim keeps plan==burn honest but ships awkward copy — a master
    opened on "Certified organic starts". One text call asks for the same
    message written inside the real budget."""

    @staticmethod
    def _plan(hook="Certified organic starts here"):
        from workflows.video.nodes import _normalize_shot_plan

        return _normalize_shot_plan(
            {
                "hook_line": hook,
                "shots": [
                    {
                        "index": 1,
                        "duration_s": 3,
                        "scene": "SCENE CONTEXT: open",
                        "overlay_text": hook,
                    },
                    {"index": 2, "duration_s": 3, "scene": "SCENE CONTEXT: mid"},
                ],
                "caption": "cap",
                "hashtags": [],
                "cta": "Shop now",
            }
        )

    def test_a_fitting_hook_is_not_reported(self):
        plan = self._plan("Organic, honestly")
        assert plan["hook_trimmed"] is False

    def test_rewrite_replaces_the_stump(self, monkeypatch):
        import asyncio

        from workflows.video import nodes

        async def fake_chat(*args, **kwargs):
            return '{"hook": "Organic starts here"}'

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        plan = asyncio.run(nodes._rewrite_hook_to_fit(self._plan()))
        assert plan["shots"][0]["overlay_text"] == "Organic starts here"
        assert plan["hook_trimmed"] is False
        # The accepted rewrite must itself survive the burn whole.
        rendered = nodes._wrap_overlay_text(
            plan["shots"][0]["overlay_text"], nodes._HOOK_WRAP_CHARS
        )
        assert rendered.replace("\\N", " ") == "Organic starts here"

    def test_rewrite_that_still_does_not_fit_keeps_the_trim(self, monkeypatch):
        import asyncio

        from workflows.video import nodes

        async def fake_chat(*args, **kwargs):
            return '{"hook": "Certified organic goodness starts right here today"}'

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        plan = asyncio.run(nodes._rewrite_hook_to_fit(self._plan()))
        assert plan["shots"][0]["overlay_text"] == "Certified organic starts"
        assert plan["hook_trimmed"] is True

    def test_rewrite_failure_keeps_the_trim(self, monkeypatch):
        import asyncio

        from workflows.video import nodes

        async def fake_chat(*args, **kwargs):
            raise RuntimeError("model down")

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        plan = asyncio.run(nodes._rewrite_hook_to_fit(self._plan()))
        assert plan["shots"][0]["overlay_text"] == "Certified organic starts"
        assert plan["hook_trimmed"] is True

    def test_untrimmed_plan_makes_no_call(self, monkeypatch):
        import asyncio

        from workflows.video import nodes

        async def fake_chat(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("no rewrite call for a fitting hook")

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        plan = asyncio.run(nodes._rewrite_hook_to_fit(self._plan("Organic, honestly")))
        assert plan["shots"][0]["overlay_text"] == "Organic, honestly"


class TestDistributeDurations:
    def test_proportional_and_sums_exactly(self):
        out = _distribute_durations([2.5, 2.0, 2.0], 26.0)
        assert sum(out) == pytest.approx(26.0)
        assert out[0] == pytest.approx(10.0, abs=0.05)
        assert out[1] == pytest.approx(8.0, abs=0.05)

    def test_zero_weights_fall_back_to_equal_split(self):
        out = _distribute_durations([0, 0, 0, 0], 20.0)
        assert out == [5.0, 5.0, 5.0, 5.0]

    def test_zero_total_or_empty(self):
        assert _distribute_durations([3, 3], 0) == [0.0, 0.0]
        assert _distribute_durations([], 20.0) == []


class TestOverlayEvents:
    def test_timing_windows_are_padded_and_capped(self):
        events = _overlay_events(
            _overlay_shots(["First line", "Second line"]), [5.0, 5.0], ""
        )
        assert len(events) == 2
        # The hook waits for the first frame to land, then holds at most
        # _CAPTION_MAX_HOLD_S — the footage runs clean to the cut after.
        assert events[0]["style"] == "Hook"
        assert events[0]["start"] == pytest.approx(video_nodes._HOOK_START_S)
        assert events[0]["end"] == pytest.approx(
            video_nodes._HOOK_START_S + video_nodes._CAPTION_MAX_HOLD_S
        )
        assert events[1]["style"] == "Overlay"
        assert events[1]["start"] == pytest.approx(5.2)
        assert events[1]["end"] == pytest.approx(
            5.2 + video_nodes._CAPTION_MAX_HOLD_S
        )

    def test_final_shot_shows_cta_with_cta_style(self):
        events = _overlay_events(
            _overlay_shots(["Hook line", "Benefit", "Payoff"]),
            [5.0, 5.0, 5.0],
            "Shop now",
        )
        assert events[-1]["text"] == "Shop now"
        assert events[-1]["style"] == "CTA"
        # Non-final shots keep their own lines
        assert events[0]["text"] == "Hook line"

    def test_empty_cta_keeps_final_overlay_text(self):
        events = _overlay_events(
            _overlay_shots(["One", "Two"]), [5.0, 5.0], ""
        )
        assert events[-1]["text"] == "Two"
        assert events[-1]["style"] == "Overlay"

    def test_empty_texts_are_skipped(self):
        events = _overlay_events(
            _overlay_shots(["Hook", "", "Beat"]), [5.0, 5.0, 5.0], ""
        )
        assert [e["text"] for e in events] == ["Hook", "Beat"]

    def test_a_split_hook_never_shows_its_text_twice(self):
        # _split_to_min_shots can halve the first beat into two rendered
        # shots carrying the same line. The duplicate must not be promoted
        # into the proof slot — the hook would show twice.
        events = _overlay_events(
            _overlay_shots(["Same beat", "Same beat", "Next"]),
            [4.0, 4.0, 4.0],
            "",
        )
        texts = [e["text"] for e in events]
        assert texts.count("Same beat") == 1
        assert "Next" in texts

    def test_cta_spans_both_halves_of_a_split_final_shot(self):
        # _split_to_min_shots halves the last planned beat into two rendered
        # shots sharing plan index 2 — the CTA must cover BOTH, not just the
        # trailing half.
        shots = [
            {"index": 1, "duration_s": 5.0, "overlay_text": "Hook"},
            {"index": 1, "duration_s": 5.0, "overlay_text": "Hook"},
            {"index": 2, "duration_s": 5.0, "overlay_text": "Payoff"},
            {"index": 2, "duration_s": 5.0, "overlay_text": "Payoff"},
        ]
        events = _overlay_events(shots, [5.0, 5.0, 5.0, 5.0], "Shop now")
        assert len(events) == 2
        cta = events[-1]
        assert cta["text"] == "Shop now"
        assert cta["style"] == "CTA"
        # Starts at the FIRST half of the split beat (10s), not 15s.
        assert cta["start"] == pytest.approx(10.2)
        assert cta["end"] == pytest.approx(19.85)

    def test_beats_are_hook_one_proof_and_cta(self):
        events = _overlay_events(
            _overlay_shots(["Hook", "Benefit", "Payoff"]),
            [5.0, 5.0, 5.0],
            "Shop now",
        )
        assert [e["style"] for e in events] == ["Hook", "Overlay", "CTA"]
        assert events[-1]["start"] == pytest.approx(10.2)

    def test_sub_minimum_window_is_dropped(self):
        events = _overlay_events(_overlay_shots(["Blink"]), [0.4], "")
        assert events == []

    def test_a_captioned_every_shot_plan_still_renders_as_beats(self):
        # Plans captioned every beat before 2026-08-19 ("should [not]
        # necessarily be throughout the video" — user). Whatever the plan
        # says, the burn shows at most hook + _MAX_MID_CAPTIONS + CTA.
        for count in (6, 7, 8):
            shots = _overlay_shots([f"Beat {i + 1}" for i in range(count)])
            durations = [TARGET_TOTAL_S / count] * count
            events = _overlay_events(shots, durations, "Shop now")
            assert len(events) == 2 + video_nodes._MAX_MID_CAPTIONS
            assert [e["style"] for e in events][0] == "Hook"
            assert [e["style"] for e in events][-1] == "CTA"
            assert all(
                e["end"] - e["start"] >= _OVERLAY_MIN_ON_SCREEN_S for e in events
            )

    def test_unreadably_short_windows_hold_instead_of_flashing(self):
        # Legacy single-call path: an 8-beat plan spread over one ~5s clip
        # would flash each line for 0.6s — a short beat holds into the clean
        # windows that follow it instead.
        shots = _overlay_shots([f"Beat {i + 1}" for i in range(8)])
        events = _overlay_events(shots, [0.625] * 8, "")
        assert events
        assert all(
            e["end"] - e["start"] >= _OVERLAY_MIN_ON_SCREEN_S for e in events
        )
        # Windows stay in order and never overlap.
        for earlier, later in zip(events, events[1:]):
            assert earlier["end"] <= later["start"]
        # The opening line survives — holding never reorders the arc.
        assert events[0]["text"] == "Beat 1"

    def test_holding_never_swallows_the_cta(self):
        # A short line may absorb its neighbours but must stop at the
        # Overlay → CTA boundary, or the reel would lose its call to action.
        shots = _overlay_shots(["Hook", "Beat", "Payoff"])
        events = _overlay_events(shots, [0.6, 0.6, 0.6], "Shop now")
        assert events
        assert events[-1]["text"] == "Shop now"
        assert events[-1]["style"] == "CTA"

    def test_short_cta_takes_its_dwell_from_the_line_before_it(self):
        # 8 beats over one ~5s fallback clip: the CTA owns only 0.625s of it
        # and would be padded away — it borrows from the held line instead.
        shots = _overlay_shots([f"Beat {i + 1}" for i in range(8)])
        events = _overlay_events(shots, [0.625] * 8, "Shop now")
        assert events[-1]["text"] == "Shop now"
        assert events[-1]["style"] == "CTA"
        # The CTA lands on at least the readable minimum (float slack aside).
        assert (
            events[-1]["end"] - events[-1]["start"]
            >= _OVERLAY_MIN_ON_SCREEN_S - 0.01
        )
        for earlier, later in zip(events, events[1:]):
            assert earlier["end"] <= later["start"]

    def test_the_proof_slot_goes_to_the_longest_middle_window(self):
        shots = _overlay_shots(["One", "Two", "Three"])
        events = _overlay_events(shots, [3.0, 3.0, 3.0], "")
        # Equal windows: the LATER beat wins the proof slot — a proof lands
        # after the story has set it up.
        assert [e["text"] for e in events] == ["One", "Three"]
        longer_mid = _overlay_events(shots, [3.0, 5.0, 3.0], "")
        assert [e["text"] for e in longer_mid] == ["One", "Two"]


class TestBrandAccentHex:
    def test_palette_accent_preferred(self):
        brand = {"color_palette": {"primary": "#111111", "accent": "#f59e0b"}}
        assert _brand_accent_hex(brand) == "#f59e0b"

    def test_falls_back_to_primary_then_legacy_colors(self):
        assert _brand_accent_hex({"color_palette": {"primary": "#222222"}}) == "#222222"
        brand = {"brand_guidelines": {"colors": {"accent": "0b9ef5"}}}
        assert _brand_accent_hex(brand) == "#0b9ef5"

    def test_json_string_palette_and_missing(self):
        assert _brand_accent_hex({"color_palette": '{"accent": "#abcdef"}'}) == "#abcdef"
        assert _brand_accent_hex({}) is None
        assert _brand_accent_hex({"color_palette": {"accent": "tomato"}}) is None


class TestBuildOverlayAss:
    def _events(self):
        return _overlay_events(
            _overlay_shots(["Hook line here", "Benefit beat"]),
            [5.0, 5.0],
            "Shop now",
        )

    def test_document_structure_and_animation_tags(self):
        doc = _build_overlay_ass(self._events(), "#f59e0b")
        assert "PlayResX: 1080" in doc
        assert "PlayResY: 1920" in doc
        assert f"Style: Hook,Poppins,{video_nodes._HOOK_FONT_SIZE}," in doc
        assert f"Style: Overlay,Poppins,{_OVERLAY_FONT_SIZE}," in doc
        # Amber reads 3.2:1 on the caption card's worst backdrop — above the
        # large-text floor — so the CTA takes the brand accent.
        assert f"Style: CTA,Poppins,{_CTA_FONT_SIZE},&H000B9EF5," in doc
        # Two beats (hook + CTA), each riding its own rounded card.
        assert doc.count("Dialogue:") == 4
        assert doc.count(",Card,,") == 2
        assert ",Scrim,," not in doc
        # The hook is high-centre; the CTA bottom-left on the safe baseline.
        hx, hy = video_nodes._HOOK_POS
        assert f"\\an5\\move({hx},{hy + 24},{hx},{hy},0,220)" in doc
        assert "\\an1\\move(80,1444,80,1420,0,220)" in doc
        assert "\\fad(200,260)" in doc
        # The hook enters after the first frame lands.
        assert "0:00:00.35" in doc

    def test_a_low_contrast_accent_is_demoted_to_white(self):
        doc = _build_overlay_ass(self._events(), "#555555")
        assert f"Style: CTA,Poppins,{_CTA_FONT_SIZE},&H00FFFFFF," in doc

    def test_no_accent_falls_back_to_white_cta(self):
        doc = _build_overlay_ass(self._events(), None)
        assert f"Style: CTA,Poppins,{_CTA_FONT_SIZE},&H00FFFFFF," in doc

    def test_metacharacters_escaped_in_dialogue(self):
        events = _overlay_events(
            _overlay_shots(["Buy {now} 50\\ off"]), [5.0], ""
        )
        doc = _build_overlay_ass(events)
        dialogue = [
            ln
            for ln in doc.splitlines()
            if ln.startswith("Dialogue:") and ",Card,," not in ln
        ][0]
        text_part = dialogue.split("}", 1)[1]
        assert "{" not in text_part and "}" not in text_part
        assert "\\" not in text_part.replace("\\N", "")


class TestBurnCmd:
    def test_master_spec_and_audio_copy(self):
        cmd = _burn_cmd("/tmp/in.mp4", "/tmp/o.ass", "/tmp/out.mp4", "/fonts")
        joined = " ".join(cmd)
        assert "ass=/tmp/o.ass:fontsdir=/fonts,fps=30,format=yuv420p" in joined
        assert "-crf 19" in joined
        assert "-preset medium" in joined
        assert "-profile:v high" in joined
        assert "-g 60" in joined
        assert "-c:a copy" in joined
        assert "+faststart" in joined
        assert cmd[-1] == "/tmp/out.mp4"

    def test_fontsdir_omitted_when_none(self):
        cmd = _burn_cmd("in.mp4", "o.ass", "out.mp4", None)
        assert "fontsdir" not in " ".join(cmd)

    def test_filter_path_escapes_colons_and_backslashes(self):
        assert _filter_path("C:\\tmp\\o.ass") == "C\\:/tmp/o.ass"

    def test_filter_path_escapes_commas_quotes_and_semicolons(self):
        # An unescaped comma would split the -vf chain and make ffmpeg parse
        # the rest of the path as another filter.
        assert _filter_path("/tmp/a,b/o.ass") == "/tmp/a\\,b/o.ass"
        assert _filter_path("/tmp/it's/o.ass") == "/tmp/it\\'s/o.ass"
        assert _filter_path("/tmp/a;b/o.ass") == "/tmp/a\\;b/o.ass"

    def test_comma_in_path_cannot_split_the_vf_chain(self):
        cmd = _burn_cmd("in.mp4", "/tmp/reel,1/o.ass", "out.mp4", None)
        vf = cmd[cmd.index("-vf") + 1]
        # Exactly one unescaped comma: the one separating ass= from fps=.
        unescaped = [
            i
            for i, ch in enumerate(vf)
            if ch == "," and (i == 0 or vf[i - 1] != "\\")
        ]
        assert len(unescaped) == 2  # ass=...,fps=30,format=yuv420p
        assert vf.startswith("ass=/tmp/reel\\,1/o.ass,")


# ── Burn stage (ffmpeg mocked) ─────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


class TestBurnOverlaysStage:
    def test_ffmpeg_failure_keeps_unburned_master(self, monkeypatch):
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: True)

        def failing_ffmpeg(args, timeout=300):
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout=b"",
                stderr=b"No such filter: 'ass'",
            )

        monkeypatch.setattr(video_nodes, "_run_ffmpeg", failing_ffmpeg)
        out, meta = _run(
            _burn_overlays(
                b"MASTER",
                _overlay_shots(["Hook", "Beat", "More", "End"]),
                "Shop now",
                {},
                durations=[5.0, 5.0, 5.0, 5.0],
            )
        )
        assert out == b"MASTER"
        assert meta["overlay_burn"].startswith("failed:")
        assert "ass" in meta["overlay_burn"]
        assert "overlay_lines" not in meta

    def test_ffmpeg_unavailable(self, monkeypatch):
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: False)
        out, meta = _run(
            _burn_overlays(
                b"MASTER", _overlay_shots(["Hook"]), "Go", {}, durations=[5.0]
            )
        )
        assert out == b"MASTER"
        assert meta["overlay_burn"] == "failed:ffmpeg unavailable"

    def test_no_text_at_all_is_skipped_without_ffmpeg(self, monkeypatch):
        monkeypatch.setattr(
            video_nodes, "_ffmpeg_ok", lambda: pytest.fail("must not be called")
        )
        out, meta = _run(
            _burn_overlays(b"MASTER", _overlay_shots(["", ""]), "", {})
        )
        assert out == b"MASTER"
        assert meta["overlay_burn"].startswith("skipped:")

    def test_success_returns_burned_bytes_and_line_count(self, monkeypatch):
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: True)
        captured = {}

        def ok_ffmpeg(args, timeout=300):
            captured["args"] = args
            with open(args[-1], "wb") as fh:
                fh.write(b"BURNED")
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"", stderr=b""
            )

        monkeypatch.setattr(video_nodes, "_run_ffmpeg", ok_ffmpeg)
        out, meta = _run(
            _burn_overlays(
                b"MASTER",
                _overlay_shots(["Hook", "Beat", "More", "End"]),
                "Shop now",
                {"color_palette": {"accent": "#f59e0b"}},
                durations=[5.0, 5.0, 5.0, 5.0],
            )
        )
        assert out == b"BURNED"
        assert meta == {
            "overlay_burn": "ok",
            # Beat system: hook + one proof + CTA, whatever the plan says.
            "overlay_lines": 3,
            # No grade_params passed, so nothing was graded in this pass.
            "graded_shots": 0,
        }
        vf = captured["args"][captured["args"].index("-vf") + 1]
        assert vf.startswith("ass=")

    def test_single_shot_distribution_uses_probed_duration(self, monkeypatch):
        # durations=None → the planned beats are spread proportionally
        # across the clip's REAL ffprobe duration (30s here, plan sums 10s).
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: True)
        monkeypatch.setattr(
            video_nodes, "_probe_shot", lambda path: {"duration": 30.0}
        )
        written = {}

        def ok_ffmpeg(args, timeout=300):
            with open(args[-1], "wb") as fh:
                fh.write(b"BURNED")
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"", stderr=b""
            )

        real_write_text = video_nodes._write_text

        def capture_write_text(path, text):
            if path.endswith(".ass"):
                written["ass"] = text
            real_write_text(path, text)

        monkeypatch.setattr(video_nodes, "_run_ffmpeg", ok_ffmpeg)
        monkeypatch.setattr(video_nodes, "_write_text", capture_write_text)
        shots = _overlay_shots(["Hook", "Beat", "End"], duration=0)
        for s, d in zip(shots, (5.0, 3.0, 2.0)):
            s["duration_s"] = d
        out, meta = _run(_burn_overlays(b"MASTER", shots, "Shop now", {}))
        assert meta["overlay_burn"] == "ok"
        doc = written["ass"]
        # Shot 1 spans 0..15s of the 30s clip → the hook enters at 0.35s and
        # holds its capped beat, not the whole window.
        assert "0:00:00.35" in doc
        assert "0:00:03.55" in doc
        # CTA (final 6s window: 24..30) → 24.2..29.85, uncapped.
        assert "0:00:24.20" in doc
        assert "0:00:29.85" in doc


class TestRenderVideoOverlayWiring:
    def test_multi_shot_master_gets_burn_pass(self, monkeypatch):
        from tests.test_video_multishot import _Harness, _state

        h = _Harness(monkeypatch)
        state = _state([4, 4, 4, 4, 4])
        for i, shot in enumerate(state["shot_plan"]["shots"]):
            shot["overlay_text"] = f"Beat {i + 1}"
        state["brand"] = {"color_palette": {"accent": "#f59e0b"}}
        result = asyncio.run(video_nodes.render_video(state))

        assert result.get("status") != "failed"
        meta = result["video_meta"]
        assert meta["overlay_burn"] == "ok"
        # Beat system with an end card: the card carries the CTA, so the
        # burn shows hook + one proof line only.
        assert meta["overlay_lines"] == 2
        burn_calls = [
            c
            for c in h.ffmpeg_calls
            if any(str(a).startswith("ass=") for a in c)
        ]
        assert len(burn_calls) == 1
        assert "-c:a" in burn_calls[0]

    def test_legacy_path_burn_failure_never_fails_item(self, monkeypatch):
        from tests.test_video_multishot import _Harness, _state

        _Harness(monkeypatch)
        # No ffmpeg → degraded single-call render AND a failed (not fatal)
        # burn pass: the item keeps the unburned clip.
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: False)
        state = _state([4, 4, 4, 4, 4])
        state["shot_plan"]["shots"][0]["overlay_text"] = "Hook"
        result = asyncio.run(video_nodes.render_video(state))

        assert result.get("status") != "failed"
        assert result["video_bytes"] == b"CLIP1"
        meta = result["video_meta"]
        assert meta["overlay_burn"] == "failed:ffmpeg unavailable"


class TestCtaFitsItsBox:
    """The CTA is set larger than the overlay lines, so it fits fewer
    characters per line. Wrapping it at the overlay budget silently dropped
    the tail of a real reel's CTA ("...shelf to table." vanished), so the
    budget is enforced at plan time and honoured at burn time.
    """

    def test_cta_budget_is_smaller_than_overlay_budget(self):
        assert video_nodes._CTA_FONT_SIZE > video_nodes._OVERLAY_FONT_SIZE
        assert video_nodes._CTA_WRAP_CHARS < video_nodes._OVERLAY_WRAP_CHARS
        assert (
            video_nodes._CTA_MAX_CHARS
            == video_nodes._CTA_WRAP_CHARS * video_nodes._OVERLAY_MAX_LINES
        )

    def test_normalize_clamps_cta_to_its_own_budget(self):
        plan = _plan_with_cta("See clearer choices from shelf to table.")
        cta = video_nodes._normalize_shot_plan(plan)["cta"]

        assert len(cta) <= video_nodes._CTA_MAX_CHARS
        # Whole words only — never a mid-word cut.
        assert all(
            w in "See clearer choices from shelf to table.".split()
            for w in cta.split()
        )

    def test_short_cta_survives_untouched(self):
        plan = _plan_with_cta("Shop the range")
        assert video_nodes._normalize_shot_plan(plan)["cta"] == "Shop the range"

    def test_burned_cta_never_drops_words(self):
        plan = _plan_with_cta("See clearer choices from shelf to table.")
        cta = video_nodes._normalize_shot_plan(plan)["cta"]
        wrapped = video_nodes._wrap_overlay_text(cta, video_nodes._CTA_WRAP_CHARS)

        # Every word that survived normalization also survives the wrap.
        assert wrapped.replace("\\N", " ").split() == cta.split()
        assert len(wrapped.split("\\N")) <= video_nodes._OVERLAY_MAX_LINES

    def test_cta_event_wraps_at_cta_width(self):
        events = [
            {"text": "Shop certified today", "style": "CTA", "start": 0.0, "end": 4.0}
        ]
        doc = video_nodes._build_overlay_ass(events, accent_hex=None)
        # The card plate is a vector drawing, not type — measure the text only.
        dialogue = [
            ln
            for ln in doc.splitlines()
            if ln.startswith("Dialogue:") and ",Card,," not in ln
        ]

        assert len(dialogue) == 1
        for line in dialogue[0].split(",")[-1].split("\\N"):
            # Strip any leading ASS override block before measuring.
            visible = line.split("}")[-1]
            assert len(visible) <= video_nodes._CTA_WRAP_CHARS


def _plan_with_cta(cta: str) -> dict:
    return {
        "hook_line": "Hook",
        "caption": "Caption",
        "hashtags": [],
        "cta": cta,
        "shots": [
            {"index": i + 1, "duration_s": 5.0, "overlay_text": f"Beat {i + 1}",
             "scene": "SCENE CONTEXT: x"}
            for i in range(6)
        ],
    }
