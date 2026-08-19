"""The BC item card must be consulted first — with the identifier that exists.

The user's standing instruction is that product photos come from the Business
Central item card BEFORE any web lookup. The chain in image_sourcing.py was
written that way and its tests passed, but they all supplied
``product_sku="SKU-1"``. In production ``sku`` is empty on every one of the
1,251 synced products across all three brands; the identifier lives in
``bc_item_no``. So the BC step was skipped for every product ever generated,
and sourcing fell through to the supplier and web-search steps — exactly what
the instruction rules out.

These tests pin the identifier, not just the order.
"""

import asyncio

import pytest

from workflows.content import image_sourcing


@pytest.fixture
def spy(monkeypatch):
    """Record what each step of the chain was asked for."""
    seen = {"bc": [], "supplier": [], "web": []}

    async def fake_bc(identifier, *a, **k):
        seen["bc"].append(identifier)
        return "products/p1/gallery/bc_X.jpg" if identifier == "MSJZRCA01-7-BLACK" else None

    async def fake_scrape(url):
        seen["supplier"].append(url)
        return []

    async def fake_web(**kwargs):
        seen["web"].append(kwargs.get("product_name"))
        return None

    monkeypatch.setattr(image_sourcing, "get_product_image_from_bc", fake_bc)
    monkeypatch.setattr(image_sourcing, "scrape_product_images", fake_scrape)
    monkeypatch.setattr(image_sourcing, "find_product_image", fake_web)
    return seen


def _run(**kwargs):
    return asyncio.run(image_sourcing.source_product_image(**kwargs))


class TestBCIdentifier:
    def test_bc_item_no_is_used_when_sku_is_empty(self, spy):
        """The production shape: empty sku, populated bc_item_no."""
        result = _run(
            product_sku="",
            bc_item_no="MSJZRCA01-7-BLACK",
            product_name="RingConn, Smart Ring Gen 2 RCA-01, Size 7 Black",
            supplier_url="https://supplier.example/p",
        )
        assert spy["bc"] == ["MSJZRCA01-7-BLACK"]
        assert result.source == "bc"
        assert result.confidence == 1.0

    def test_bc_short_circuits_before_any_web_lookup(self, spy):
        _run(
            bc_item_no="MSJZRCA01-7-BLACK",
            product_name="RingConn Smart Ring",
            supplier_url="https://supplier.example/p",
        )
        assert spy["supplier"] == [], "scraped the supplier despite a BC picture"
        assert spy["web"] == [], "searched the web despite a BC picture"

    def test_sku_still_works_when_it_is_the_only_identifier(self, spy):
        _run(product_sku="MSJZRCA01-7-BLACK", product_name="RingConn Smart Ring")
        assert spy["bc"] == ["MSJZRCA01-7-BLACK"]

    def test_bc_item_no_wins_over_a_stale_sku(self, spy):
        _run(product_sku="OLD-SKU", bc_item_no="MSJZRCA01-7-BLACK", product_name="x")
        assert spy["bc"] == ["MSJZRCA01-7-BLACK"]

    def test_no_identifier_at_all_skips_bc_but_says_so(self, spy, caplog):
        with caplog.at_level("WARNING"):
            _run(product_name="Unmatched product", supplier_url="https://s.example/p")
        assert spy["bc"] == []
        assert any("skipping the authoritative item-card" in r.getMessage()
                   for r in caplog.records), (
            "silently skipping the BC step is how this went unnoticed"
        )

    def test_missing_bc_picture_still_falls_through(self, spy):
        # BC returning nothing is normal (no picture on the card); the chain
        # must continue rather than give up.
        _run(bc_item_no="NO-PICTURE", product_name="x", supplier_url="https://s.example/p")
        assert spy["bc"] == ["NO-PICTURE"]
        assert spy["supplier"] == ["https://s.example/p"]
        assert spy["web"] == ["x"]

    def test_a_bc_failure_is_not_fatal(self, monkeypatch, spy):
        async def boom(*a, **k):
            raise RuntimeError("BC 401")

        monkeypatch.setattr(image_sourcing, "get_product_image_from_bc", boom)
        result = _run(bc_item_no="X", product_name="x")
        # BC access is currently 401 pending an admin grant; that must degrade
        # to lifestyle handling, not raise.
        assert result.needs_manual is True
