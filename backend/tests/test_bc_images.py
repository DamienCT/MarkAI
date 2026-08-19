"""Tests for Business-Central-first product image sourcing (backend side).

Covers app/services/bc_image_service.py and the ordering guarantee in
app/api/v1/products.py: the BC item card is tried before the browser-worker
web search, a BC miss or error falls through cleanly, and a BC picture skips
the vision gate that web results must pass.

No network: httpx is faked inside app.services.bc_api.
"""

import json
import os
import types
import uuid

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import products as products_api
from app.services import bc_api, bc_image_service
from app.services.bc_api import BCConfig

TENANT = "11111111-1111-1111-1111-111111111111"
COMPANY_ID = "22222222-2222-2222-2222-222222222222"
ITEM_ID = "33333333-3333-3333-3333-333333333333"

JPEG = b"\xff\xd8\xff\xe0" + b"bc-item-card-picture" * 8


def _cfg(**overrides):
    base = dict(
        tenant_id=TENANT,
        client_id="client-id",
        client_secret="client-secret",
        environment="Production",
        base_url="https://api.businesscentral.dynamics.com",
        enabled=True,
    )
    base.update(overrides)
    return BCConfig(**base)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        return json.dumps(self._json) if self._json is not None else ""

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aclose(self):
        return None

    async def get(self, url, **kwargs):
        return self._dispatch("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._dispatch("POST", url, kwargs)

    def _dispatch(self, method, url, kwargs):
        self.calls.append((method, url))
        for fragment, handler in self.routes.items():
            if fragment in url:
                if callable(handler):
                    return handler(url, kwargs)
                return handler
        raise AssertionError(f"unrouted {method} {url}")


def _routes(company_name="Naturespan"):
    link = (
        f"https://api.businesscentral.dynamics.com/v2.0/{TENANT}/Production"
        f"/api/v2.0/companies({COMPANY_ID})/items({ITEM_ID})"
        f"/picture({ITEM_ID})/pictureContent"
    )
    return {
        "login.microsoftonline.com": FakeResponse(
            200, {"access_token": "tok", "expires_in": 3600}
        ),
        "/companies?": FakeResponse(200, {"value": []}),
        "pictureContent": FakeResponse(
            200, content=JPEG, headers={"content-type": "image/jpeg"}
        ),
        "/picture": FakeResponse(
            200,
            {
                "id": ITEM_ID,
                "width": 500,
                "height": 496,
                "contentType": "image/jpeg",
                "pictureContent@odata.mediaReadLink": link,
            },
        ),
        "/items?": FakeResponse(200, {"value": [{"id": ITEM_ID, "number": "SKU-1"}]}),
        "/companies": FakeResponse(
            200, {"value": [{"id": COMPANY_ID, "name": company_name}]}
        ),
    }


def _patch_httpx(monkeypatch, routes):
    client = FakeClient(routes)
    monkeypatch.setattr(bc_api.httpx, "AsyncClient", lambda **kw: client)
    return client


def _product(**overrides):
    """A stand-in Product: plain object, so no lazy-load machinery fires."""
    attrs = dict(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        name="Hemp Flour 250g",
        bc_item_no="SKU-1",
        sku="SKU-1",
        bc_company="Naturespan",
        vendor_name="Naturespan Ltd",
        image_urls=[],
        primary_image_url=None,
    )
    attrs.update(overrides)
    return types.SimpleNamespace(**attrs)


@pytest.fixture(autouse=True)
def _clean_state():
    bc_api.reset_cache()
    yield
    bc_api.reset_cache()


# ── bc_image_service ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_fetch_from_bc_returns_gallery_ready_dict(monkeypatch):
    _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    img = await bc_image_service.fetch_product_image_from_bc(_product())

    assert img is not None
    assert img["source"] == "business_central"
    assert img["image_data"] == JPEG
    assert img["content_type"] == "image/jpeg"
    assert img["size_bytes"] == len(JPEG)
    assert img["bc_item_no"] == "SKU-1"
    assert img["extension"] == "jpg"


@pytest.mark.anyio
async def test_credentials_absent_disables_the_path_without_any_call(monkeypatch):
    client = _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(
        bc_image_service, "build_bc_config", lambda: _cfg(client_secret="")
    )

    assert await bc_image_service.fetch_product_image_from_bc(_product()) is None
    assert client.calls == []


@pytest.mark.anyio
async def test_disable_flag_switches_the_path_off(monkeypatch):
    client = _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg(enabled=False))

    assert await bc_image_service.fetch_product_image_from_bc(_product()) is None
    assert client.calls == []


@pytest.mark.anyio
async def test_product_without_bc_company_is_skipped(monkeypatch):
    client = _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    product = _product(bc_company=None)
    product.brand = None
    assert await bc_image_service.fetch_product_image_from_bc(product) is None
    assert client.calls == []


@pytest.mark.anyio
async def test_bc_error_returns_none_and_does_not_raise(monkeypatch):
    routes = _routes()
    routes["/companies"] = FakeResponse(500, {"error": "boom"})
    _patch_httpx(monkeypatch, routes)
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    assert await bc_image_service.fetch_product_image_from_bc(_product()) is None


def test_bc_company_falls_back_to_the_brand():
    product = _product(bc_company=None)
    product.brand = types.SimpleNamespace(bc_company="Healthspan")
    assert bc_image_service.bc_company_for(product) == "Healthspan"


def test_bc_company_survives_an_unloaded_lazy_relationship():
    """Product.brand is lazy — touching it can raise MissingGreenlet."""

    class _Lazy:
        bc_company = None

        @property
        def brand(self):
            raise RuntimeError("MissingGreenlet")

    assert bc_image_service.bc_company_for(_Lazy()) == ""


def test_has_bc_image_detects_an_already_synced_picture():
    assert bc_image_service.has_bc_image(_product()) is False
    assert (
        bc_image_service.has_bc_image(
            _product(image_urls=[{"source": "web_search"}])
        )
        is False
    )
    assert (
        bc_image_service.has_bc_image(
            _product(image_urls=[{"source": "business_central"}])
        )
        is True
    )


# ── the API path prefers BC ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_endpoint_helper_prefers_bc_and_skips_the_web_worker(monkeypatch):
    _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    worker_calls = []

    async def _worker(product):
        worker_calls.append(product)
        return {"url": "https://web/x.jpg", "content_type": "image/jpeg",
                "size_bytes": 9, "image_data": b"web"}

    monkeypatch.setattr(products_api, "_fetch_one_product_image_via_worker", _worker)

    img = await products_api._fetch_one_product_image(_product())

    assert img["source"] == "business_central"
    assert worker_calls == [], "web search must not run when BC has the picture"


@pytest.mark.anyio
async def test_endpoint_helper_falls_back_to_web_when_bc_has_no_picture(monkeypatch):
    routes = _routes()
    routes["/items?"] = FakeResponse(200, {"value": []})  # SKU not in BC
    _patch_httpx(monkeypatch, routes)
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    async def _worker(product):
        return {"url": "https://web/x.jpg", "content_type": "image/jpeg",
                "size_bytes": 9, "image_data": b"web"}

    monkeypatch.setattr(products_api, "_fetch_one_product_image_via_worker", _worker)

    img = await products_api._fetch_one_product_image(_product())
    assert img["url"] == "https://web/x.jpg"
    assert img.get("source") is None  # tagged web_search downstream


@pytest.mark.anyio
async def test_endpoint_helper_falls_back_when_bc_errors(monkeypatch):
    routes = _routes()
    routes["/companies"] = FakeResponse(401, {"error": "Authentication_InvalidCredentials"})
    _patch_httpx(monkeypatch, routes)
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    async def _worker(product):
        return {"url": "https://web/x.jpg", "content_type": "image/jpeg",
                "size_bytes": 9, "image_data": b"web"}

    monkeypatch.setattr(products_api, "_fetch_one_product_image_via_worker", _worker)

    img = await products_api._fetch_one_product_image(_product())
    assert img["url"] == "https://web/x.jpg"


@pytest.mark.anyio
async def test_existing_bc_image_short_circuits_the_api_call(monkeypatch):
    """A repeat fetch must not re-download bytes we already hold."""
    client = _patch_httpx(monkeypatch, _routes())
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    async def _worker(product):
        return {"url": "https://web/x.jpg", "content_type": "image/jpeg",
                "size_bytes": 9, "image_data": b"web"}

    monkeypatch.setattr(products_api, "_fetch_one_product_image_via_worker", _worker)

    product = _product(
        image_urls=[
            {"url": "products/x/gallery/bc_SKU-1.jpg", "source": "business_central"}
        ]
    )
    img = await products_api._fetch_one_product_image(product)

    assert img["url"] == "https://web/x.jpg"
    assert client.calls == [], "BC must not be re-queried for a picture we already have"


@pytest.mark.anyio
async def test_endpoint_helper_returns_none_when_both_sources_miss(monkeypatch):
    routes = _routes()
    routes["/items?"] = FakeResponse(200, {"value": []})
    _patch_httpx(monkeypatch, routes)
    monkeypatch.setattr(bc_image_service, "build_bc_config", lambda: _cfg())

    async def _worker(product):
        return None

    monkeypatch.setattr(products_api, "_fetch_one_product_image_via_worker", _worker)

    assert await products_api._fetch_one_product_image(_product()) is None


# ── gallery persistence ──────────────────────────────────────────────────


class _FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _patch_minio(monkeypatch):
    uploads = []

    async def _ensure_bucket():
        return None

    async def _upload(object_name, data, content_type):
        uploads.append((object_name, data, content_type))
        return object_name

    monkeypatch.setattr(products_api.minio_service, "ensure_bucket", _ensure_bucket)
    monkeypatch.setattr(products_api.minio_service, "upload_file", _upload)
    monkeypatch.setattr(products_api, "flag_modified", lambda obj, field: None)
    return uploads


@pytest.mark.anyio
async def test_bc_image_is_saved_with_its_own_source_and_becomes_primary(monkeypatch):
    uploads = _patch_minio(monkeypatch)
    product = _product(
        image_urls=[{"url": "products/x/gallery/web_1.jpg", "source": "web_search"}],
        primary_image_url="products/x/gallery/web_1.jpg",
    )
    img = {
        "url": "bc://Naturespan/items/SKU-1",
        "content_type": "image/jpeg",
        "size_bytes": len(JPEG),
        "image_data": JPEG,
        "source": "business_central",
        "bc_item_no": "SKU-1",
        "extension": "jpg",
    }

    entry = await products_api._save_image_to_gallery(_FakeDB(), product, img)

    assert entry["source"] == "business_central"
    expected = f"products/{product.id}/gallery/bc_SKU-1.jpg"
    assert entry["object_name"] == expected
    assert uploads == [(expected, JPEG, "image/jpeg")]
    # Authoritative: the ERP picture takes over as primary.
    assert product.primary_image_url == expected
    # The pre-existing web image is kept in the gallery, not destroyed.
    assert len(product.image_urls) == 2


@pytest.mark.anyio
async def test_refetching_bc_replaces_instead_of_duplicating(monkeypatch):
    _patch_minio(monkeypatch)
    product = _product()
    img = {
        "url": "bc://Naturespan/items/SKU-1",
        "content_type": "image/jpeg",
        "size_bytes": len(JPEG),
        "image_data": JPEG,
        "source": "business_central",
        "bc_item_no": "SKU-1",
        "extension": "jpg",
    }

    await products_api._save_image_to_gallery(_FakeDB(), product, img)
    await products_api._save_image_to_gallery(_FakeDB(), product, img)

    assert len(product.image_urls) == 1


@pytest.mark.anyio
async def test_bc_item_number_cannot_escape_the_products_prefix(monkeypatch):
    uploads = _patch_minio(monkeypatch)
    product = _product()
    img = {
        "url": "bc://Naturespan/items/x",
        "content_type": "image/jpeg",
        "size_bytes": len(JPEG),
        "image_data": JPEG,
        "source": "business_central",
        "bc_item_no": "../../evil",
        "extension": "jpg",
    }

    await products_api._save_image_to_gallery(_FakeDB(), product, img)

    object_name = uploads[0][0]
    assert ".." not in object_name
    assert object_name.startswith(f"products/{product.id}/gallery/")


@pytest.mark.anyio
async def test_web_image_keeps_its_existing_naming_and_source(monkeypatch):
    uploads = _patch_minio(monkeypatch)
    product = _product()
    img = {
        "url": "https://web/x.jpeg",
        "content_type": "image/jpeg",
        "size_bytes": 3,
        "image_data": b"web",
    }

    entry = await products_api._save_image_to_gallery(_FakeDB(), product, img)

    assert entry["source"] == "web_search"
    assert uploads[0][0] == f"products/{product.id}/gallery/web_1.jpg"


# ── the vendored copy must not drift ─────────────────────────────────────


def test_bc_api_is_byte_identical_to_the_agents_copy():
    """One implementation, two Docker build contexts.

    backend/ and agents/ are built from disjoint contexts so the protocol file
    is vendored rather than imported. This test is what stops the two copies
    from forking — edit agents/shared/tools/bc_api.py and copy it across.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    mine = os.path.join(here, "..", "app", "services", "bc_api.py")
    theirs = os.path.join(here, "..", "..", "agents", "shared", "tools", "bc_api.py")
    if not os.path.exists(theirs):
        pytest.skip("agents tree not present (running inside the backend container)")
    with open(mine, "rb") as fh:
        a = fh.read()
    with open(theirs, "rb") as fh:
        b = fh.read()
    assert a == b, (
        "bc_api.py has drifted between backend/ and agents/. "
        "Edit agents/shared/tools/bc_api.py and copy it to "
        "backend/app/services/bc_api.py."
    )
