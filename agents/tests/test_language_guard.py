"""The five items that shipped in French, and the copy that must not trip.

Fixtures marked REAL are verbatim from the 2026-08-18 Naturespan plan — the run
that motivated the guard. The false-positive tests matter more than the
detection tests: this brand's catalogue is full of French supplier names, and a
guard that flags "Moulin des Moines" every week is one nobody reads.
"""

import pytest

from shared.language_guard import check_items, detect_non_english, format_flags

# Supplier and brand names the copy is legitimately about.
NAMES = [
    "Naturespan",
    "Moulin des Moines",
    "L'Angelus",
    "Le Pain des Fleurs",
    "Autour du Riz",
    "Celnat",
    "Ecocert",
    "Eurofeuille",
]


class TestTheItemsThatShipped:
    @pytest.mark.parametrize(
        "title",
        [
            "Du bio vérifiable, enfin",  # REAL — was mid-render when caught
            "J-1: du bio vérifié",  # REAL
            "Back to School (Rentrée 2027)",  # REAL
            "After-school goûter inspiration with trusted organic brands",  # REAL
            "Rentrée 2027 lunchbox and snack routine",  # REAL
        ],
    )
    def test_each_is_flagged(self, title):
        assert detect_non_english(title, allow=NAMES), (
            f"{title!r} shipped to a customer-facing surface in French"
        )

    def test_a_short_unaccented_french_line_is_still_caught(self):
        # No accents and no rare vocabulary — the earlier marker list had
        # 'vos' but not 'vous', so this class of CTA slipped through.
        assert detect_non_english("Rendez-vous demain", allow=NAMES)

    def test_a_french_brief_is_flagged_even_when_mostly_english(self):
        brief = (
            "Scheduled on the event date, this rentrée post highlights first-day "
            "breakfast and goûter ideas built from produits certifies AB & Ecocert."
        )
        markers = detect_non_english(brief, allow=NAMES)
        assert {"rentrée", "goûter", "produits"} <= set(markers)


class TestSupplierNamesSurvive:
    """These are what the copy is FOR — flagging them makes the guard useless."""

    @pytest.mark.parametrize(
        "text",
        [
            "Breakfast with Moulin des Moines cereals and Celnat grains",
            "Le Pain des Fleurs crackers, stocked all week",
            "Autour du Riz pasta for a fast weeknight dinner",
            "L'Angelus spreads arrive Thursday",
            "AB, Ecocert and Eurofeuille certification, explained simply",
        ],
    )
    def test_clean_english_around_french_names(self, text):
        assert detect_non_english(text, allow=NAMES) == []

    def test_without_the_allowlist_the_name_does_trip_it(self):
        # Documents why callers must pass names: the guard cannot tell a
        # supplier from a sentence on its own.
        assert detect_non_english("Moulin des Moines cereals") == ["des"]


class TestEnglishIsNotFlagged:
    @pytest.mark.parametrize(
        "text",
        [
            "Open the organic aisle today",
            "Proof you can actually see",
            "Dinner starts with a clean pour",  # 'pour' is French AND English
            "From bottle to cafe table",
            "A softer countdown starts here",
            "Your organic shop, clarified",
            "Pour the oil, then season to taste",
            "The chat with our founder, in full",  # 'chat' is French AND English
            "One coin, one cause: our round-up scheme",
            "Sale ends Sunday",
            "Our son-in-law's favourite loaf",
        ],
    )
    def test_no_false_positive(self, text):
        assert detect_non_english(text, allow=NAMES) == [], text

    @pytest.mark.parametrize(
        "text",
        ["A café table for two", "Résumé of our first year", "Crème brûlée, made simply"],
    )
    def test_naturalised_loanwords_pass(self, text):
        assert detect_non_english(text, allow=NAMES) == [], text

    def test_empty_and_missing_are_quiet(self):
        assert detect_non_english("") == []
        assert detect_non_english(None) == []  # type: ignore[arg-type]


class TestCheckItems:
    def test_reports_index_title_and_fields(self):
        items = [
            {"title": "Open the organic aisle today", "content_brief": "A clean shelf."},
            {"title": "Du bio vérifiable, enfin", "content_brief": "Le magasin ouvre."},
        ]
        flagged = check_items(items, allow=NAMES)
        assert len(flagged) == 1
        assert flagged[0]["index"] == 1
        assert "title" in flagged[0]["fields"] and "content_brief" in flagged[0]["fields"]

    def test_nothing_is_rewritten(self):
        items = [{"title": "Du bio vérifiable, enfin"}]
        check_items(items, allow=NAMES)
        assert items[0]["title"] == "Du bio vérifiable, enfin", (
            "the guard reports; a silent machine translation would hide the defect"
        )

    def test_non_dict_entries_are_skipped(self):
        assert check_items([None, "x", {"title": "Rentrée"}], allow=NAMES)[0]["index"] == 2

    def test_format_is_one_readable_line(self):
        flagged = check_items([{"title": "J-1: du bio vérifié"}], allow=NAMES)
        out = format_flags(flagged)
        assert "du" in out and "vérifié" in out and "\n" not in out

    def test_format_truncates_a_long_run(self):
        items = [{"title": f"Rentrée {i}"} for i in range(25)]
        out = format_flags(check_items(items, allow=NAMES), limit=5)
        assert "+20 more" in out
