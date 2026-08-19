"""Burned lines are read alone, so they have to stand alone.

A delivered reel held "AB Ecocert Eurofeuille," on screen for a full beat.
Two defects in one line: a trailing comma promising a continuation the next
cut never delivers, and a certification body's name transcribed off the pack
instead of a claim a shopper cares about.
"""

import pytest

from workflows.video import nodes


class TestFragmentClosing:
    @pytest.mark.parametrize("raw,expected", [
        ("AB Ecocert Eurofeuille,", "AB Ecocert Eurofeuille"),
        ("Certified organic —", "Certified organic"),
        ("Dinner starts with a...", "Dinner starts with a..."),
        ("Made for mornings;", "Made for mornings"),
        ("Real proof:", "Real proof"),
        ("Certified organic…", "Certified organic"),
    ])
    def test_trailing_punctuation_is_dropped(self, raw, expected):
        # "..." as three dots is left alone; only the ellipsis character and
        # the connective punctuation are treated as an open end.
        out = nodes._close_fragment(raw)
        assert out == expected or out == expected.rstrip(".")

    @pytest.mark.parametrize("raw,expected", [
        ("Certified organic and", "Certified organic"),
        ("Every bottle checked for", "Every bottle checked"),
        ("Good food starts with", "Good food starts"),
        ("Proof you can see, and", "Proof you can see"),
    ])
    def test_a_dangling_connective_is_dropped(self, raw, expected):
        assert nodes._close_fragment(raw) == expected

    @pytest.mark.parametrize("line", [
        "Shop the pantry range",
        "Certified organic, every bottle",
        "Dinner starts with a clean pour",
        "Open today",
        "Why does it matter?",
        "Taste the difference!",
    ])
    def test_a_complete_line_is_untouched(self, line):
        assert nodes._close_fragment(line) == line

    def test_a_line_that_is_only_a_connective_survives(self):
        # Stripping to nothing would lose the beat's line entirely; one word
        # is better than none.
        assert nodes._close_fragment("and") == "and"

    def test_empty_and_none_are_safe(self):
        assert nodes._close_fragment("") == ""
        assert nodes._close_fragment(None) == ""

    def test_repeated_tails_are_all_closed(self):
        assert nodes._close_fragment("Certified organic, and —") == (
            "Certified organic"
        )

    def test_the_cleaner_closes_fragments_too(self):
        # The guard has to run on the path the plan actually takes.
        assert nodes._clean_overlay_text("Certified organic and") == (
            "Certified organic"
        )
        assert nodes._clean_overlay_text("AB Ecocert Eurofeuille,") == (
            "AB Ecocert Eurofeuille"
        )

    def test_closing_runs_after_the_wrap_budget_not_before(self):
        # Dropping a trailing word to fit the box can EXPOSE a connective
        # that was mid-sentence: "Good food starts with a clean pour" trimmed
        # to "Good food starts with" must not ship ending on "with".
        out = nodes._clean_overlay_text(
            "Good food starts with a really clean pour",
        )
        last = out.split()[-1].lower() if out else ""
        assert last not in nodes._DANGLING_WORDS, out


class TestPlanInstructions:
    @pytest.fixture
    def prompt(self):
        import inspect

        return inspect.getsource(nodes.plan_shots)

    def test_the_json_example_does_not_anchor_one_duration(self, prompt):
        # A single "duration_s": 4.0 in the example was copied onto every
        # beat, and the reel ticked like a metronome.
        assert '"duration_s": 3.0' in prompt
        assert '"duration_s": 5.0' in prompt

    def test_pacing_is_stated_as_a_requirement(self, prompt):
        assert "PACING" in prompt
        assert "differ by a full second" in prompt

    def test_lines_are_required_to_stand_alone(self, prompt):
        assert "EVERY LINE STANDS ALONE" in prompt
        assert "connective word" in prompt

    def test_certification_transcription_is_called_out(self, prompt):
        assert "Certification names" in prompt


class TestPacingSurvivesTheFitter:
    def test_varied_weights_stay_varied_after_fitting(self):
        # The fitter reallocates to hit the 30s target; it must not flatten
        # the plan's pacing into equal beats while doing it.
        shots = [
            {"index": i + 1, "duration_s": d, "scene": "x"}
            for i, d in enumerate([3.0, 3.0, 5.0, 4.0, 3.0, 5.0, 4.0])
        ]
        fitted, dropped = nodes._fit_shot_durations(shots)
        assert dropped == []
        durations = [s["duration_s"] for s in fitted]
        assert max(durations) - min(durations) >= 1.0, (
            f"pacing flattened to {durations}"
        )

    def test_uniform_weights_still_produce_a_valid_reel(self):
        shots = [
            {"index": i + 1, "duration_s": 4.0, "scene": "x"}
            for i in range(7)
        ]
        fitted, _ = nodes._fit_shot_durations(shots)
        total = sum(s["duration_s"] for s in fitted)
        assert total == pytest.approx(nodes.TARGET_TOTAL_S, abs=0.05)


class TestWidowsAreRebalanced:
    """A greedy wrap fills each line to the brim and strands the remainder.

    "See you on September 1" wrapped to "See you on September" / "1" and
    shipped that way in a delivered reel — a lone numeral on its own line
    under a 76px caption, which is the sort of thing a reader notices before
    they read the words.
    """

    def test_the_line_that_shipped(self):
        assert nodes._wrap_overlay_text("See you on September 1") == (
            "See you on\\NSeptember 1"
        )

    def test_a_balanced_line_is_left_alone(self):
        assert nodes._wrap_overlay_text("Certified products, honestly sourced") == (
            "Certified products,\\Nhonestly sourced"
        )

    def test_one_line_has_no_widow_to_fix(self):
        assert nodes._rebalance_widow(["Short line"], 30) == ["Short line"]
        assert nodes._rebalance_widow([], 30) == []

    def test_it_refuses_when_the_move_would_overflow(self):
        # A widow is a blemish; an overflowing box is a defect. The box wins.
        # "cdefghij 1" is 10 characters against a 9-character line budget.
        lines = ["ab cdefghij", "1"]
        assert nodes._rebalance_widow(lines, 9) == lines

    def test_it_refuses_when_the_donor_line_is_one_word(self):
        # Moving it would only relocate the widow to the line above.
        assert nodes._rebalance_widow(["Supercalifragilistic", "1"], 30) == [
            "Supercalifragilistic", "1"
        ]

    @pytest.mark.parametrize("widow", ("1", "a", "to", "and"))
    def test_short_stranded_words_are_pulled_down(self, widow):
        out = nodes._rebalance_widow(["one two three", widow], 30)
        assert out == ["one two", f"three {widow}"]

    def test_a_legitimate_short_closing_word_is_kept(self):
        # Four characters reads as a word, not a fragment — rebalancing it
        # would churn lines that are already fine.
        assert nodes._rebalance_widow(["one two three", "hype"], 30) == [
            "one two three", "hype"
        ]

    def test_the_box_budget_still_holds_after_rebalancing(self):
        for text in (
            "See you on September 1",
            "Grand Baie opens with Tamarin",
            "One week to certified organic",
        ):
            for line in nodes._wrap_overlay_text(text).split("\\N"):
                assert len(line) <= nodes._OVERLAY_WRAP_CHARS, (text, line)
