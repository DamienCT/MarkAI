"""Suppliers never surface in anything a customer sees.

The defect that forced this module: a Naturespan post reached review on
2026-08-19 reading "sourced through ACCORD BIO" in every platform caption,
with "ACCORD BIO" in the tag list — the supplier the user had just ordered
suppressed everywhere, for every brand. The brand's own proof points were the
source, so the guard has to work on both sides of the model: strip names from
the context going in, and from the copy coming out.
"""

from shared import suppliers


TERMS = ["ACCORD BIO", "Biodis", "Segafredo Zanetti S.P.A"]


class TestOutputScrub:
    def test_the_caption_that_shipped(self):
        text = (
            "In Mauritius, organic is not tightly controlled. We focus on "
            "proof: AB & Ecocert / Eurofeuille certified products, sourced "
            "with ACCORD BIO.\n\nCoteaux Nantais Apricot Jam, 690g is one "
            "easy pantry pick.\n\nShop with confidence."
        )
        clean, hits = suppliers.strip_supplier_mentions(text, TERMS)
        assert "ACCORD" not in clean
        assert hits == ["ACCORD BIO"]
        # The sentence survives minus the sourcing clause.
        assert "certified products." in clean
        # Paragraph structure survives.
        assert "\n\n" in clean
        assert "Shop with confidence." in clean

    def test_clean_text_is_returned_byte_identical(self):
        text = "Real proof.\n\nEvery bottle checked.\n\nShop today."
        clean, hits = suppliers.strip_supplier_mentions(text, TERMS)
        assert clean == text
        assert hits == []

    def test_a_sentence_that_is_only_a_credit_is_dropped(self):
        text = "Great taste. Sourced through ACCORD BIO. Shop today."
        clean, _ = suppliers.strip_supplier_mentions(text, TERMS)
        assert clean == "Great taste. Shop today."

    def test_corporate_suffix_variants_match(self):
        # The vendor record says "S.P.A", prose drops it.
        clean, hits = suppliers.strip_supplier_mentions(
            "Espresso by Segafredo Zanetti, imported weekly. Taste it.",
            TERMS,
        )
        assert "Segafredo" not in clean
        assert hits == ["Segafredo Zanetti S.P.A"]

    def test_keep_lets_the_featured_products_own_brand_through(self):
        # Moulin des Moines is a vendor AND the brand on the pack being sold.
        terms = [*TERMS, "Moulin Des Moines"]
        keep = suppliers.product_own_terms("Moulin des Moines, Spelt Flour, 1kg")
        clean, hits = suppliers.strip_supplier_mentions(
            "Moulin des Moines Spelt Flour is back in stock.", terms, keep=keep
        )
        assert "Moulin des Moines" in clean
        assert hits == []

    def test_word_boundaries_hold(self):
        # "Biodis" must not fire inside "biodiversity".
        clean, hits = suppliers.strip_supplier_mentions(
            "Farming that protects biodiversity, every day.", TERMS
        )
        assert hits == []
        assert "biodiversity" in clean


class TestTagFilter:
    def test_squashed_hashtag_matches(self):
        kept, dropped = suppliers.filter_tags(
            ["CertifiedOrganic", "AccordBio", "Mauritius"], TERMS
        )
        assert kept == ["CertifiedOrganic", "Mauritius"]
        assert dropped == ["AccordBio"]

    def test_tag_carrying_the_name_inside_is_dropped_not_rewritten(self):
        kept, dropped = suppliers.filter_tags(["ShopAccordBioToday"], TERMS)
        assert kept == []
        assert dropped == ["ShopAccordBioToday"]

    def test_keep_protects_the_featured_brand_tag(self):
        terms = [*TERMS, "Pranarom"]
        kept, dropped = suppliers.filter_tags(
            ["Pranarom", "AccordBio"],
            terms,
            keep=suppliers.product_own_terms("Pranarom, Essential Oil, 10ml"),
        )
        assert kept == ["Pranarom"]
        assert dropped == ["AccordBio"]


class TestContextScrub:
    def test_brand_description_is_neutralised(self):
        cfg = {
            "id": "b1",
            "name": "Naturespan",
            "description": (
                "Founded on 20+ years of organic expertise via the ACCORD BIO "
                "purchasing group (17,000+ references)."
            ),
            "brand_guidelines": {
                "dos": [
                    "Use verified proof points: 2,600+ certified products, "
                    "ACCORD BIO purchasing group (17,000+ references)"
                ],
                "suppliers_never_mention": ["ACCORD BIO"],
            },
        }
        out = suppliers.scrub_brand_dict(cfg, ["ACCORD BIO"])
        assert "ACCORD" not in out["description"]
        assert "our sourcing network" in out["description"]
        assert "ACCORD" not in out["brand_guidelines"]["dos"][0]
        # The guard's own config key survives its own scrub.
        assert out["brand_guidelines"]["suppliers_never_mention"] == ["ACCORD BIO"]

    def test_structure_and_non_strings_are_untouched(self):
        cfg = {"id": "b1", "settings": {"n": 3, "flag": True}, "name": "X"}
        out = suppliers.scrub_brand_dict(cfg, ["ACCORD BIO"])
        assert out == cfg

    def test_no_terms_returns_the_same_object_shape(self):
        cfg = {"description": "mentions ACCORD BIO"}
        assert suppliers.scrub_brand_dict(cfg, []) == cfg


class TestDeepPayloadScrub:
    def test_platform_dicts_and_tag_lists(self):
        payload = {
            "caption": "Products sourced through ACCORD BIO. Shop today.",
            "platform_adaptations": {
                "youtube": {
                    "description": "Backed by ACCORD BIO. Real proof you can taste.",
                    "tags": ["organic", "ACCORD BIO"],
                },
                "instagram": {"hashtags": ["AccordBio", "OrganicPantry"]},
            },
        }
        out, hits = suppliers.scrub_content_payload(payload, TERMS)
        assert "ACCORD" not in str(out)
        assert out["platform_adaptations"]["youtube"]["tags"] == ["organic"]
        assert out["platform_adaptations"]["instagram"]["hashtags"] == [
            "OrganicPantry"
        ]
        assert "Real proof you can taste." in out["platform_adaptations"][
            "youtube"
        ]["description"]
        assert "ACCORD BIO" in hits

    def test_shot_plan_fields_survive_when_clean(self):
        plan = {
            "hook_line": "Dinner starts clean",
            "shots": [{"scene": "slow dolly over a kitchen counter,\nwarm light"}],
        }
        out, hits = suppliers.scrub_content_payload(plan, TERMS)
        assert out == plan
        assert hits == []


class TestPackOwner:
    def test_leading_segment_is_the_owner(self):
        assert suppliers.pack_owner("Coteaux Nantais, Apricot Jam, 690g") == (
            "Coteaux Nantais"
        )

    def test_empty_name_is_safe(self):
        assert suppliers.pack_owner("") == ""
        assert suppliers.product_own_terms("") == frozenset()


class TestSubBrandVoice:
    """vendor_name is a purchasing relationship, not a voice."""

    def test_a_supplier_vendor_never_speaks(self):
        from workflows.content.nodes import _resolve_sub_brand

        brand = {"name": "Naturespan", "brand_guidelines": {}}
        product = {"vendor_name": "Biodis"}
        assert _resolve_sub_brand(product, brand) == "Naturespan"

    def test_an_allowlisted_sub_brand_speaks(self):
        from workflows.content.nodes import _resolve_sub_brand

        brand = {
            "name": "FancyFinds",
            "brand_guidelines": {"sub_brand_voices": ["Horizon"]},
        }
        product = {"vendor_name": "Horizon"}
        assert _resolve_sub_brand(product, brand) == "Horizon"

    def test_no_product_keeps_the_brand_voice(self):
        from workflows.content.nodes import _resolve_sub_brand

        assert _resolve_sub_brand({}, {"name": "Naturespan"}) == "Naturespan"


class TestRuleWiring:
    def test_brand_context_block_carries_the_supplier_rule(self):
        from shared.brand_context import build_brand_context_block

        block = build_brand_context_block({"name": "X"})
        assert "SUPPLIERS — HARD RULE" in block

    def test_english_rule_no_longer_licenses_supplier_names(self):
        from shared.brand_context import ENGLISH_ONLY_RULE

        assert "a supplier," not in ENGLISH_ONLY_RULE
        assert "banned outright" in ENGLISH_ONLY_RULE

    def test_swap_call_sites_use_pack_owner_not_vendor(self):
        import inspect

        import worker
        from workflows.content import nodes as content_nodes

        regen = inspect.getsource(worker._handle_image_regeneration)
        assert "_pack_owner(product_name)" in regen
        swap = inspect.getsource(content_nodes._replace_product_in_generated_image)
        assert "pack_owner(product_name)" in swap
        assert 'vendor_name=vendor_name' not in swap

    def test_store_content_scrubs_before_persisting(self):
        import inspect

        from workflows.content import nodes as content_nodes

        src = inspect.getsource(content_nodes.store_content_node)
        assert "scrub_content_payload" in src
        assert "supplier_terms_for_brand" in src


def test_supplier_terms_merge_vendors_and_config(monkeypatch):
    import asyncio

    async def fake_query(sql, params=None):
        return [
            {"vendor_name": "Biodis"},
            {"vendor_name": "Moulin Des Moines"},
            {"vendor_name": ""},
        ]

    import shared.tools.database as db

    monkeypatch.setattr(db, "execute_query", fake_query)
    suppliers._cache.clear()
    cfg = {"brand_guidelines": {"suppliers_never_mention": ["ACCORD BIO"]}}
    terms = asyncio.run(suppliers.supplier_terms_for_brand("b-1", cfg))
    assert set(terms) == {"Biodis", "Moulin Des Moines", "ACCORD BIO"}
    # Longest first so multi-word names are removed before substrings could be.
    assert terms == sorted(terms, key=len, reverse=True)


def test_supplier_terms_survive_a_dead_database(monkeypatch):
    import asyncio

    async def dead_query(sql, params=None):
        raise RuntimeError("db down")

    import shared.tools.database as db

    monkeypatch.setattr(db, "execute_query", dead_query)
    suppliers._cache.clear()
    cfg = {"brand_guidelines": {"suppliers_never_mention": ["ACCORD BIO"]}}
    terms = asyncio.run(suppliers.supplier_terms_for_brand("b-2", cfg))
    assert terms == ["ACCORD BIO"]
