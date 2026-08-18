"""Tests for brand-scoped product lookup/upsert (BC sync cross-brand fix)."""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper (Approval references it)
import app.models  # noqa: F401 — registers all model mappers so Product can configure
from app.models.product import Product
from app.services.product_service import get_product_by_bc_item_no, upsert_from_bc

BRAND_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
BRAND_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeResult:
    """Mimics the SQLAlchemy Result -> scalars() -> all() chain."""

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _fake_db(rows):
    db = MagicMock()
    db.execute = AsyncMock(return_value=_FakeResult(rows))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.anyio
async def test_lookup_filters_on_brand_id_and_item_no():
    db = _fake_db([])

    await get_product_by_bc_item_no(db, "ITEM-001", BRAND_A)

    stmt = db.execute.call_args[0][0]
    compiled = stmt.compile()
    sql = str(compiled)
    assert "products.brand_id" in sql
    assert "products.bc_item_no" in sql
    assert "LIMIT" in sql.upper()
    assert BRAND_A in compiled.params.values()
    assert "ITEM-001" in compiled.params.values()


@pytest.mark.anyio
async def test_lookup_returns_none_when_no_match():
    db = _fake_db([])
    result = await get_product_by_bc_item_no(db, "ITEM-001", BRAND_A)
    assert result is None


@pytest.mark.anyio
async def test_lookup_duplicates_return_first_with_warning(caplog):
    first = Product(brand_id=BRAND_A, bc_item_no="ITEM-001", name="First")
    second = Product(brand_id=BRAND_A, bc_item_no="ITEM-001", name="Second")
    db = _fake_db([first, second])

    with caplog.at_level(logging.WARNING, logger="app.services.product_service"):
        result = await get_product_by_bc_item_no(db, "ITEM-001", BRAND_A)

    assert result is first
    assert any("Duplicate products" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_upsert_create_uses_caller_brand_id():
    """A stale brand_id inside the data payload must not win over the caller's."""
    db = _fake_db([])
    data = {"brand_id": BRAND_B, "name": "Widget"}

    product = await upsert_from_bc(db, "ITEM-001", data, brand_id=BRAND_A)

    assert product.brand_id == BRAND_A
    assert product.bc_item_no == "ITEM-001"
    db.add.assert_called_once_with(product)
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_upsert_update_never_reparents_brand():
    existing = Product(
        brand_id=BRAND_A, bc_item_no="ITEM-001", name="Old name", is_active=True
    )
    db = _fake_db([existing])
    data = {"brand_id": BRAND_B, "name": "New name", "is_active": False}

    product = await upsert_from_bc(db, "ITEM-001", data, brand_id=BRAND_A)

    assert product is existing
    assert product.brand_id == BRAND_A  # never overwritten by sync data
    assert product.name == "New name"  # regular fields still update
    assert product.is_active is True  # user-controlled field preserved
    db.add.assert_not_called()


@pytest.mark.anyio
async def test_upsert_lookup_is_brand_scoped():
    """The upsert's SELECT must carry the brand_id filter end-to-end."""
    db = _fake_db([])

    await upsert_from_bc(db, "ITEM-001", {"name": "Widget"}, brand_id=BRAND_A)

    stmt = db.execute.call_args[0][0]
    compiled = stmt.compile()
    assert "products.brand_id" in str(compiled)
    assert BRAND_A in compiled.params.values()
