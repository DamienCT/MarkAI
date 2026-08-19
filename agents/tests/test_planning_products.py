"""Tests for product-aware planning: catalog sampling + product matching."""

import asyncio
import os
import sys

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.planning.nodes as planning_nodes
from workflows.planning.nodes import (
    _PRODUCT_MATCH_STOPWORDS,
    _PRODUCT_WINDOW,
    _catalog_sample,
    _format_catalog_for_prompt,
    _match_product,
    _normalize_product_name,
)


def _product(pid: str, name: str, sku: str = "") -> dict:
    return {"id": pid, "name": name, "sku": sku or f"SKU-{pid}"}


CATALOG = [
    _product("1", "Gelée Royale Bio 25g"),
    _product("2", "Miel de Lavande 500g"),
    _product("3", "Vitamin C Serum"),
    _product("4", "Shampooing Solide Argan"),
]


# ── _normalize_product_name ──────────────────────────────────────────


def test_normalize_lowercases_strips_punctuation_and_collapses_spaces():
    assert _normalize_product_name("  Miel  de LAVANDE, 500g!! ") == "miel de lavande 500g"
    assert _normalize_product_name(None) == ""
    assert _normalize_product_name("---") == ""


# ── _match_product: exact ────────────────────────────────────────────


def test_match_exact_normalized():
    product, outcome = _match_product("Gelée Royale Bio 25g", CATALOG)
    assert outcome == "exact"
    assert product["id"] == "1"


def test_match_exact_survives_case_and_punctuation_noise():
    product, outcome = _match_product("gelée ROYALE bio, 25g!", CATALOG)
    assert outcome == "exact"
    assert product["id"] == "1"


# ── _match_product: containment ──────────────────────────────────────


def test_match_containment_query_inside_catalog_name():
    product, outcome = _match_product("Miel de Lavande", CATALOG)
    assert outcome == "containment"
    assert product["id"] == "2"


def test_match_containment_catalog_name_inside_query():
    product, outcome = _match_product("Organic Miel de Lavande 500g Premium", CATALOG)
    assert outcome == "containment"
    assert product["id"] == "2"


def test_containment_is_token_bounded_not_substring():
    # "tea" is a substring of "steamer" but must NOT match it.
    catalog = [_product("9", "Steamer Deluxe")]
    product, outcome = _match_product("tea", catalog)
    assert product is None
    assert outcome == "no_match"


def test_single_token_query_never_containment_matches():
    # A bare head noun is contained in a long tail of unrelated entries —
    # accepting it would bind an arbitrary product to the calendar item.
    catalog = [
        _product("1", "Huile Essentielle de Lavande 10ml"),
        _product("2", "Huile de Coco Vierge 250ml"),
    ]
    assert _match_product("Huile", catalog) == (None, "no_match")
    assert _match_product("Lavande", catalog) == (None, "no_match")


def test_single_token_query_still_matches_exactly():
    catalog = [_product("1", "Lavande"), _product("2", "Miel de Lavande 500g")]
    product, outcome = _match_product("lavande!", catalog)
    assert outcome == "exact"
    assert product["id"] == "1"


def test_two_significant_tokens_are_enough_for_containment():
    catalog = [_product("1", "Huile Essentielle de Lavande 10ml")]
    product, outcome = _match_product("Huile Lavande", catalog)
    assert outcome == "token_overlap"
    assert product["id"] == "1"


def test_the_is_not_a_stopword_so_tea_products_match():
    # Accent-stripped French "thé" normalizes to "the" — filtering it as an
    # English article would erase the head noun of every tea product.
    assert "the" not in _PRODUCT_MATCH_STOPWORDS
    catalog = [_product("t", "The Vert Bio 50g"), _product("m", "Miel de Lavande")]
    product, outcome = _match_product("The Vert", catalog)
    assert outcome == "containment"
    assert product["id"] == "t"


def test_containment_prefers_closest_length_candidate():
    catalog = [
        _product("a", "Collagen Powder Vanilla Flavour 500g Deluxe Edition"),
        _product("b", "Collagen Powder 300g"),
    ]
    product, outcome = _match_product("Collagen Powder", catalog)
    assert outcome == "containment"
    assert product["id"] == "b"


# ── _match_product: token overlap ────────────────────────────────────


def test_match_token_overlap():
    # {miel, 500g} shared with "miel de lavande 500g" = 2/3 of the shorter
    # name's significant tokens (stopword "de" ignored) → >= 60%.
    product, outcome = _match_product("Lavender Miel 500g", CATALOG)
    assert outcome == "token_overlap"
    assert product["id"] == "2"


def test_token_overlap_below_threshold_is_no_match():
    # Only {serum} shared with "vitamin c serum" → 1/2 = 50% < 60%.
    product, outcome = _match_product("Retinol Serum", CATALOG)
    assert product is None
    assert outcome == "no_match"


def test_token_overlap_tie_broken_by_longest_match():
    # Both candidates share {cacao, nibs} = 100% of the shorter name's
    # significant tokens (neither is a token-bounded containment of the
    # query) — the tie goes to the longest normalized name.
    catalog = [
        _product("short", "Nibs Cacao"),
        _product("long", "Cacao Raw Nibs"),
    ]
    product, outcome = _match_product("Cacao Nibs", catalog)
    assert outcome == "token_overlap"
    assert product["id"] == "long"


# ── _match_product: edge cases ───────────────────────────────────────


def test_no_match_for_unrelated_name():
    product, outcome = _match_product("Completely Unrelated Thing", CATALOG)
    assert product is None
    assert outcome == "no_match"


def test_empty_or_missing_name_is_no_name():
    assert _match_product("", CATALOG) == (None, "no_name")
    assert _match_product(None, CATALOG) == (None, "no_name")
    assert _match_product("  ,,  ", CATALOG) == (None, "no_name")


def test_empty_catalog_never_crashes():
    assert _match_product("Miel de Lavande", []) == (None, "no_match")
    assert _match_product("Anything", [{"id": "x", "name": ""}]) == (None, "no_match")


# ── _catalog_sample ──────────────────────────────────────────────────


def test_catalog_sample_small_catalog_shown_in_full():
    names = [f"P{i}" for i in range(10)]
    for idx in (0, 1, 7):
        assert _catalog_sample(names, idx) == names


def test_catalog_sample_empty_catalog():
    assert _catalog_sample([], 0) == []
    assert _catalog_sample([], 3) == []


def test_catalog_sample_is_deterministic():
    names = [f"P{i}" for i in range(200)]
    assert _catalog_sample(names, 4) == _catalog_sample(names, 4)
    assert _catalog_sample(names, 4) == _catalog_sample(list(names), 4)


def test_catalog_sample_rotates_and_wraps():
    names = [f"P{i}" for i in range(100)]
    batch0 = _catalog_sample(names, 0, window=60)
    batch1 = _catalog_sample(names, 1, window=60)
    assert batch0 == names[:60]
    assert batch1 == names[60:] + names[:20]
    assert len(batch1) == 60
    # Different batches see different slices…
    assert batch0 != batch1
    # …and together sweep the full catalog.
    assert set(batch0) | set(batch1) == set(names)


def test_catalog_sample_respects_default_window():
    names = [f"P{i}" for i in range(1176)]
    sample = _catalog_sample(names, 0)
    assert len(sample) == _PRODUCT_WINDOW
    assert sample == names[:_PRODUCT_WINDOW]


def test_catalog_window_is_prompt_budget_sized():
    # The block is rendered as plain lines, not JSON — 40 names is the budget.
    assert _PRODUCT_WINDOW == 40


# ── _format_catalog_for_prompt ───────────────────────────────────────


def test_catalog_renders_as_plain_dash_list_not_json():
    out = _format_catalog_for_prompt(["Miel de Lavande 500g", "Gelée Royale"])
    assert out == "- Miel de Lavande 500g\n- Gelée Royale"
    # No JSON punctuation to pay tokens for.
    assert '"' not in out and "[" not in out and "{" not in out


def test_catalog_skips_blanks_and_collapses_whitespace():
    assert _format_catalog_for_prompt(["  A  B ", "", "   ", None]) == "- A B"
    assert _format_catalog_for_prompt([]) == ""


def test_catalog_truncates_at_a_line_boundary_never_mid_name():
    names = [f"Product Number {i:03d}" for i in range(200)]
    out = _format_catalog_for_prompt(names, max_length=100)
    assert len(out) <= 100
    # Every emitted line is a COMPLETE name the LLM can copy verbatim.
    assert all(line in {f"- {n}" for n in names} for line in out.split("\n"))


# ── assign_products wiring ───────────────────────────────────────────


def test_assign_products_sets_product_id_and_sku(monkeypatch):
    async def _fake_get_products(brand_id):
        return CATALOG

    monkeypatch.setattr(planning_nodes, "get_products", _fake_get_products)

    state = {
        "brand_id": "brand-1",
        "calendar_items": [
            {"theme": "a", "product_name": "Miel de Lavande"},
            {"theme": "b", "product_name": None},
            {"theme": "c", "product_name": "Unrelated Thing"},
        ],
    }
    result = asyncio.run(planning_nodes.assign_products(state))
    items = result["calendar_items"]
    assert items[0]["product_id"] == "2"
    assert items[0]["product_sku"] == "SKU-2"
    assert "product_id" not in items[1]
    assert "product_id" not in items[2]


def test_assign_products_empty_catalog_does_not_crash(monkeypatch):
    async def _fake_get_products(brand_id):
        return []

    monkeypatch.setattr(planning_nodes, "get_products", _fake_get_products)

    state = {
        "brand_id": "brand-1",
        "calendar_items": [{"theme": "a", "product_name": "Miel de Lavande"}],
    }
    result = asyncio.run(planning_nodes.assign_products(state))
    assert result["calendar_items"][0].get("product_id") is None
