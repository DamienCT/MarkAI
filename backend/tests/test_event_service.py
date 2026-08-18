"""Tests for event_service — movable-holiday is_annual enforcement."""

import pytest

from app.services.event_service import _dedup_title, coerce_is_annual


class TestCoerceIsAnnual:
    """Movable (lunar-calendar) holidays must never be stored as annual."""

    @pytest.mark.parametrize(
        "title",
        [
            "Diwali",
            "Divali celebrations",
            "Deepavali — Festival of Lights",
            "Eid ul-Fitr",
            "Eid al-Adha",
            "Ganesh Chaturthi",
            "Chinese New Year",
            "Spring Festival",
            "Thaipoosam Cavadee",
            "Cavadee",
            "Maha Shivaratree",
            "Maha Shivaratri",
            "Ougadi",
            "Ugadi",
            "Easter Sunday",
            "Ash Wednesday",
        ],
    )
    def test_movable_holidays_forced_non_annual(self, title):
        assert coerce_is_annual(title, True) is False

    @pytest.mark.parametrize(
        "title",
        [
            "Black Friday",
            "Black Friday Mega Sale",
            "Cyber Monday",
            "Thanksgiving",
            "Mother's Day",
            "Mothers Day (Mauritius)",
            "Father's Day",
            "Fathers Day Special",
        ],
    )
    def test_weekday_relative_forced_non_annual(self, title):
        # 4th-Friday / last-Sunday style dates change month/day every year.
        assert coerce_is_annual(title, True) is False

    def test_movable_holiday_case_insensitive(self):
        assert coerce_is_annual("DIWALI SPECIAL", True) is False

    @pytest.mark.parametrize(
        "title",
        [
            "Christmas",
            "Labour Day",
            "World Health Day",
            "Valentine's Day",
            "Independence Day of Mauritius",
        ],
    )
    def test_fixed_date_holidays_keep_llm_claim(self, title):
        assert coerce_is_annual(title, True) is True
        assert coerce_is_annual(title, False) is False

    def test_no_false_positive_on_substrings(self):
        # "eid" must match only as a whole word, not inside other words.
        assert coerce_is_annual("Eidsvoll Heritage Week", True) is True
        # "mother"/"friday" alone must not trip the weekday-relative pattern.
        assert coerce_is_annual("Motherland Festival", True) is True
        assert coerce_is_annual("Friday Night Market", True) is True

    def test_empty_title(self):
        assert coerce_is_annual("", True) is True


class TestDedupTitle:
    """Spelling variants must collapse to one dedup token."""

    @pytest.mark.parametrize(
        "title",
        ["Diwali", "Divali", "Deepavali", "DIVALI", "  Deepavali  "],
    )
    def test_diwali_variants_collapse(self, title):
        assert _dedup_title(title) == "diwali"

    def test_variants_normalized_inside_longer_titles(self):
        assert _dedup_title("Divali Festival of Lights") == _dedup_title(
            "Diwali Festival of Lights"
        )
        assert _dedup_title("Maha Shivaratree") == _dedup_title("Maha Shivaratri")
        assert _dedup_title("Ougadi") == _dedup_title("Ugadi")

    def test_plain_titles_just_lowercased(self):
        assert _dedup_title("  Black Friday ") == "black friday"

    def test_empty_title(self):
        assert _dedup_title("") == ""
