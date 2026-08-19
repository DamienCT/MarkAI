"""Brand hex codes must never reach an image prompt.

A bake-off run caught a local model typesetting the literal palette string —
hex codes and all — across the bottom of a generated frame, and dropping a
fabricated wordmark into the reserved logo zone. Negative-prompting "text,
words, letters, numbers, typography" did not suppress it: the model was
rendering a string we had handed it. These tests pin the words-not-hex rule.
"""

import re

from shared.color_names import describe_hex, describe_palette, parse_hex

_HEX_ANYWHERE = re.compile(r"#[0-9a-fA-F]{3,6}")


class TestParseHex:
    def test_six_digit(self):
        assert parse_hex("#1F6B3B") == (31, 107, 59)

    def test_three_digit_expands(self):
        assert parse_hex("#0f0") == (0, 255, 0)

    def test_without_hash(self):
        assert parse_hex("8CC63F") == (140, 198, 63)

    def test_rejects_words(self):
        assert parse_hex("sage") is None
        assert parse_hex("") is None
        assert parse_hex(None) is None

    def test_rejects_malformed(self):
        assert parse_hex("#12345") is None
        assert parse_hex("#zzzzzz") is None


class TestDescribeHex:
    def test_naturespan_greens_read_as_green(self):
        # The brand's real palette — the exact codes seen rendered as gibberish.
        assert "green" in describe_hex("#1F6B3B")
        assert "green" in describe_hex("#8CC63F")

    def test_dark_green_is_forest_not_just_green(self):
        assert describe_hex("#0B3D1E") == "forest green"

    def test_pale_warm_neutral_reads_as_sand_or_cream(self):
        assert describe_hex("#E8DCCC") in {"sand", "cream"}

    def test_greys_named_by_lightness_not_hue(self):
        assert describe_hex("#000000") == "near-black"
        assert describe_hex("#FFFFFF") == "off-white"
        assert describe_hex("#808080") == "mid grey"

    def test_saturated_primaries(self):
        assert "blue" in describe_hex("#1D4ED8")
        assert "red" in describe_hex("#DC2626")

    def test_non_hex_returns_none(self):
        assert describe_hex("sage") is None

    def test_never_returns_anything_hex_shaped(self):
        for code in ("#1F6B3B", "#8CC63F", "#E8DCCC", "#000", "#fff", "#DC2626"):
            assert not _HEX_ANYWHERE.search(describe_hex(code))


class TestDescribePalette:
    def test_full_palette_has_no_hex(self):
        phrase = describe_palette(
            {"primary": "#1F6B3B", "secondary": "#8CC63F", "accent": "#E8DCCC"}
        )
        assert not _HEX_ANYWHERE.search(phrase)
        assert "primary" in phrase and "secondary" in phrase and "accent" in phrase

    def test_word_palettes_pass_through(self):
        phrase = describe_palette({"primary": "sage", "accent": "warm sand"})
        assert "sage" in phrase and "warm sand" in phrase

    def test_defaults_fill_missing_roles(self):
        phrase = describe_palette(
            {"primary": "#1F6B3B"}, defaults={"accent": "#f59e0b"}
        )
        assert "primary" in phrase and "accent" in phrase
        assert not _HEX_ANYWHERE.search(phrase)

    def test_brand_value_overrides_default(self):
        phrase = describe_palette(
            {"primary": "#1F6B3B"}, defaults={"primary": "#3b82f6"}
        )
        assert "green" in phrase and "blue" not in phrase

    def test_empty_palette_yields_empty_string(self):
        # The caller drops the whole clause rather than emit a dangling label.
        assert describe_palette({}) == ""
        assert describe_palette(None) == ""

    def test_junk_values_are_skipped_not_emitted(self):
        assert describe_palette({"primary": "", "secondary": None}) == ""
