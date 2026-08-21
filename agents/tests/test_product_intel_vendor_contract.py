"""Regression tests for the product-intel persistence contract (N-06/N-07).

DB rows from ``get_products`` (SELECT * FROM products) expose
``vendor_name``/``vendor_no`` and ``primary_image_url`` — never ``vendor`` or
``image_url``. The nodes must group/read vendors via vendor_name-first and
must populate ``image_url`` + ``metadata`` (as a JSON string) on every path so
``upsert_product`` persists them.
"""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.product_intel.nodes as pi_nodes


def _db_row(pid, name, vendor_name, primary_image_url=None, metadata=None, sku=None):
    """Shape of a products row as get_products returns it (SELECT *)."""
    return {
        "id": pid,
        "brand_id": "brand-1",
        "bc_item_no": f"BC-{pid}",
        "name": name,
        "description": None,
        "category": None,
        "sku": sku,
        "vendor_name": vendor_name,
        "vendor_no": "V001",
        "unit_price": None,
        "bc_company": "co",
        "bc_location": None,
        "remaining_qty": None,
        "primary_image_url": primary_image_url,
        "metadata": metadata,
    }


# ── N-07: vendor grouping ────────────────────────────────────────────


def test_discover_brands_groups_db_rows_by_vendor_name(monkeypatch):
    rows = [
        _db_row("p1", "Olive Oil 500ml", "NatureSpan", "https://img/1.png", {"a": 1}),
        _db_row("p2", "Raw Honey 250g", "NatureSpan"),
        _db_row("p3", "Vitamin C Serum", "GlowLabs"),
    ]

    async def _get_products(brand_id):
        return rows

    async def _chat(*args, **kwargs):
        return "not json"  # force parse_llm_json onto the vendor-group fallback

    monkeypatch.setattr(pi_nodes, "get_products", _get_products)
    monkeypatch.setattr(pi_nodes, "chat_completion", _chat)

    result = asyncio.run(pi_nodes.discover_brands({"brand_id": "brand-1"}))

    mappings = result["brand_mappings"]
    assert set(mappings) == {"NatureSpan", "GlowLabs"}
    assert "Unknown" not in mappings
    assert mappings["NatureSpan"][0]["product_count"] == 2


def test_discover_brands_still_groups_legacy_vendor_key(monkeypatch):
    rows = [
        {"id": "p1", "name": "Olive Oil", "sku": "S1", "vendor": "LegacyVend", "image_url": None},
    ]

    async def _get_products(brand_id):
        return rows

    async def _chat(*args, **kwargs):
        return "not json"

    monkeypatch.setattr(pi_nodes, "get_products", _get_products)
    monkeypatch.setattr(pi_nodes, "chat_completion", _chat)

    result = asyncio.run(pi_nodes.discover_brands({"brand_id": "brand-1"}))

    assert set(result["brand_mappings"]) == {"LegacyVend"}


# ── N-06: image_url / metadata contract ──────────────────────────────


def test_discover_brands_normalizes_image_url_and_metadata(monkeypatch):
    rows = [
        _db_row("p1", "Olive Oil", "NatureSpan", "https://img/1.png", {"a": 1}),
    ]

    async def _get_products(brand_id):
        return rows

    async def _chat(*args, **kwargs):
        return "not json"

    monkeypatch.setattr(pi_nodes, "get_products", _get_products)
    monkeypatch.setattr(pi_nodes, "chat_completion", _chat)

    result = asyncio.run(pi_nodes.discover_brands({"brand_id": "brand-1"}))

    product = result["products"][0]
    # image_url lifted from primary_image_url so downstream nodes and the
    # upsert see the stored image instead of re-sourcing / nulling it.
    assert product["image_url"] == "https://img/1.png"
    # metadata handed to upsert_product as a JSON string
    assert json.loads(product["metadata"]) == {"a": 1}


def test_match_products_merges_metadata_and_upserts_json_string(monkeypatch):
    products = [
        {"sku": "A1", "name": "Olive Oil", "vendor_name": "NatureSpan", "metadata": {"seed": 1}},
    ]
    upserted = []

    async def _chat(*args, **kwargs):
        return json.dumps(
            [{"sku": "A1", "product_name": "Olive Oil", "brand_name": "NatureSpan",
              "category": "food", "is_promotable": True}]
        )

    async def _upsert(product):
        upserted.append(product)
        return "p1"

    monkeypatch.setattr(pi_nodes, "chat_completion", _chat)
    monkeypatch.setattr(pi_nodes, "upsert_product", _upsert)

    result = asyncio.run(
        pi_nodes.match_products_to_brands(
            {"brand_id": "brand-1", "products": products, "brand_mappings": {}}
        )
    )

    assert len(upserted) == 1
    md = json.loads(upserted[0]["metadata"])
    assert md["brand_name"] == "NatureSpan"
    assert md["is_promotable"] is True
    assert md["seed"] == 1  # pre-existing metadata keys survive the merge
    assert result["products"][0]["metadata"] == upserted[0]["metadata"]


def test_source_images_skips_primary_image_and_uses_vendor_name(monkeypatch):
    products = [
        _db_row("p1", "Olive Oil", "NatureSpan", primary_image_url="https://img/1.png"),
        _db_row("p2", "Raw Honey", "NatureSpan"),
    ]
    source_calls = []
    upserted = []

    async def _source(**kwargs):
        source_calls.append(kwargs)
        return SimpleNamespace(image_url="https://img/2.png")

    async def _upsert(product):
        upserted.append(product)
        return product["id"]

    monkeypatch.setattr(pi_nodes, "source_product_image", _source)
    monkeypatch.setattr(pi_nodes, "upsert_product", _upsert)

    result = asyncio.run(
        pi_nodes.source_product_images_node({"brand_id": "brand-1", "products": products})
    )

    # p1 already has a stored image → no re-sourcing, no re-upsert
    assert result["images"] == {"p1": "https://img/1.png", "p2": "https://img/2.png"}
    assert len(source_calls) == 1
    assert source_calls[0]["brand_name"] == "NatureSpan"  # not "" (N-07)
    assert len(upserted) == 1
    assert upserted[0]["id"] == "p2"
    assert upserted[0]["image_url"] == "https://img/2.png"
