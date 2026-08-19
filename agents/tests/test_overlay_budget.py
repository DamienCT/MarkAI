"""An overlay line must reach the viewer whole.

Two lines shipped a word short inside a finished 30-second master:

    "Dinner starts with a clean pour"   burned as  "Dinner starts / with a clean"
    "Certified organic, every bottle"   burned as  "Certified organic,"

Both passed the clamp. At 16 chars x 2 lines the budget was computed as the
product, 32 characters, and both lines are under it — but a greedy wrap
abandons the ragged end of every line, so the real capacity is lower than the
product and varies per line. The clamp now simulates the wrap instead of
approximating it, and the box was widened from 16x96px to 18x84px, which is the
same block width with room for two more characters.
"""

import pytest

from workflows.video import nodes

# Verbatim from rendered Naturespan reels.
SHIPPED_SHORT = [
    "Dinner starts with a clean pour",
    "Certified organic, every bottle",
]
REAL_LINES = SHIPPED_SHORT + [
    "Weeknight cooking needs",
    "Proof lives in every detail",
    "Simple pantry, real family meal",
    "Calm at the table",
    "A softer kind of discovery",
    "Open today, certified throughout",
    "Around 140 trusted brands",
]


def _wrapped(text):
    """What the burn actually puts on screen, as a list of lines."""
    cleaned = nodes._clean_overlay_text(text)
    return nodes._wrap_overlay_text(nodes._ass_escape(cleaned)).split("\\N")


class TestNoWordIsLost:
    @pytest.mark.parametrize("line", REAL_LINES)
    def test_every_real_line_survives_whole(self, line):
        assert " ".join(_wrapped(line)).split() == line.split(), (
            f"{line!r} lost a word between the plan and the screen"
        )

    @pytest.mark.parametrize("line", SHIPPED_SHORT)
    def test_the_two_that_shipped_short_now_fit(self, line):
        # Named separately so a regression points straight at the incident.
        assert line.split()[-1] in " ".join(_wrapped(line))

    def test_the_clamp_and_the_wrap_agree(self):
        """Whatever the clamp keeps, the wrap must be able to render.

        The defect was precisely a disagreement between the two: the clamp
        said a line fit and the wrap then dropped its tail, warning into a log
        nobody was reading.
        """
        for line in REAL_LINES:
            cleaned = nodes._clean_overlay_text(line)
            rendered = nodes._wrap_overlay_text(nodes._ass_escape(cleaned))
            assert rendered.replace("\\N", " ").split() == cleaned.split(), (
                f"clamp kept {cleaned!r} but the wrap could not render it"
            )


class TestClampStillClamps:
    def test_an_over_long_line_is_shortened_not_mangled(self):
        long = "Absolutely everything you could possibly want for dinner tonight"
        out = nodes._clean_overlay_text(long)
        # Dropped from the end, whole words only, and it must now fit.
        assert long.startswith(out)
        assert out.split() == out.split()  # whole words
        assert len(nodes._wrap_overlay_text(out).split("\\N")) <= nodes._OVERLAY_MAX_LINES

    def test_word_cap_still_applies(self):
        out = nodes._clean_overlay_text("one two three four five six seven eight")
        assert len(out.split()) <= nodes.MAX_OVERLAY_WORDS

    def test_a_single_oversized_word_is_kept_truncated(self):
        out = nodes._clean_overlay_text("Supercalifragilisticexpialidocious")
        assert out, "the line must not vanish entirely"
        assert len(out) <= nodes._OVERLAY_WRAP_CHARS

    def test_empty_stays_empty(self):
        assert nodes._clean_overlay_text(None) == ""
        assert nodes._clean_overlay_text("   ") == ""


class TestCTABudget:
    def test_cta_is_measured_against_its_own_larger_type(self):
        # The CTA is set larger, so it fits fewer characters per line.
        assert nodes._CTA_WRAP_CHARS < nodes._OVERLAY_WRAP_CHARS

    @pytest.mark.parametrize(
        "cta", ["Shop pantry now", "Visit us today", "Discover it in Grand Baie"]
    )
    def test_real_ctas_survive_whole(self, cta):
        cleaned = nodes._clean_overlay_text(
            cta, nodes._CTA_MAX_CHARS, nodes._CTA_WRAP_CHARS
        )
        rendered = nodes._wrap_overlay_text(cleaned, nodes._CTA_WRAP_CHARS)
        assert rendered.replace("\\N", " ").split() == cleaned.split()
        assert cleaned == cta, f"CTA {cta!r} was shortened to {cleaned!r}"
