"""Tests for Business-Central-first product image sourcing (agents side).

Covers the BC API protocol client (shared/tools/bc_api.py), the agents glue
(shared/tools/bc_images.py) and the ordering guarantee in the sourcing chain
(workflows/content/image_sourcing.py): BC item card first, supplier second,
web search last.

No network: every HTTP call goes through a fake httpx.AsyncClient patched into
the module under test, in the style of test_video_providers.py.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from shared.tools import bc_api, bc_images
from shared.tools.bc_api import BCConfig, fetch_item_picture, is_available

TENANT = "11111111-1111-1111-1111-111111111111"
COMPANY_ID = "22222222-2222-2222-2222-222222222222"
ITEM_ID = "33333333-3333-3333-3333-333333333333"

# A tiny but valid-looking JPEG payload.
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


# ── Fake httpx layer ─────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        if self._json is not None:
            return json.dumps(self._json)
        return self.content.decode("utf-8", "replace")

    def json(self):
        return self._json


class FakeClient:
    """Routes GET/POST by URL substring; records every call for assertions."""

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
                if isinstance(handler, list):
                    return handler.pop(0) if len(handler) > 1 else handler[0]
                if callable(handler):
                    return handler(url, kwargs)
                return handler
        raise AssertionError(f"unrouted {method} {url}")


def _default_routes(picture_json=None, picture_bytes=JPEG, company_name="Naturespan"):
    picture_json = (
        picture_json
        if picture_json is not None
        else {
            "id": ITEM_ID,
            "width": 500,
            "height": 496,
            "contentType": "image/jpeg",
            "pictureContent@odata.mediaReadLink": (
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT}/Production"
                f"/api/v2.0/companies({COMPANY_ID})/items({ITEM_ID})"
                f"/picture({ITEM_ID})/pictureContent"
            ),
        }
    )
    return {
        "login.microsoftonline.com": FakeResponse(
            200, {"access_token": "tok", "expires_in": 3600}
        ),
        "/companies?": FakeResponse(200, {"value": []}),
        "pictureContent": FakeResponse(
            200, content=picture_bytes, headers={"content-type": "image/jpeg"}
        ),
        "/picture": FakeResponse(200, picture_json),
        "/items?": FakeResponse(200, {"value": [{"id": ITEM_ID, "number": "SKU-1"}]}),
        "/companies": FakeResponse(
            200, {"value": [{"id": COMPANY_ID, "name": company_name}]}
        ),
    }


def _patch_httpx(monkeypatch, routes):
    client = FakeClient(routes)
    monkeypatch.setattr(bc_api.httpx, "AsyncClient", lambda **kw: client)
    return client


@pytest.fixture(autouse=True)
def _clean_state():
    bc_api.reset_cache()
    yield
    bc_api.reset_cache()


# ── bc_api: the protocol ─────────────────────────────────────────────────


def test_fetch_item_picture_returns_bytes_and_metadata(monkeypatch):
    client = _patch_httpx(monkeypatch, _default_routes())

    pic = asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1"))

    assert pic is not None
    assert pic.content == JPEG
    assert pic.content_type == "image/jpeg"
    assert pic.extension == "jpg"
    assert pic.company_id == COMPANY_ID
    assert pic.item_id == ITEM_ID
    # Hits the BC API v2.0 route, not the Fabric SQL endpoint.
    urls = " ".join(u for _, u in client.calls)
    assert f"/v2.0/{TENANT}/Production/api/v2.0/companies" in urls


def test_item_lookup_filters_on_item_number_and_escapes_quotes(monkeypatch):
    client = _patch_httpx(monkeypatch, _default_routes())

    asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "O'BRIEN-1"))

    item_calls = [u for _, u in client.calls if "/items?" in u]
    assert item_calls, "no item lookup issued"
    # OData string literals escape a quote by doubling it; the whole filter is
    # URL-encoded, so %27%27 is the doubled quote.
    assert "number%20eq%20%27O%27%27BRIEN-1%27" in item_calls[0]


def test_unknown_company_returns_none_without_item_lookup(monkeypatch):
    routes = _default_routes(company_name="SomeOtherCo")
    client = _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None
    assert not [u for _, u in client.calls if "/items?" in u]


def test_item_not_in_bc_returns_none(monkeypatch):
    routes = _default_routes()
    routes["/items?"] = FakeResponse(200, {"value": []})
    _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None


def test_item_without_picture_returns_none(monkeypatch):
    """A picture-less item still returns a picture record — just an empty one."""
    routes = _default_routes(picture_json={"id": ITEM_ID, "width": 0, "height": 0})
    _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None


def test_picture_404_returns_none(monkeypatch):
    routes = _default_routes()
    routes["/picture"] = FakeResponse(404, {"error": {"code": "NotFound"}})
    _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None


def test_missing_credentials_makes_no_http_call(monkeypatch):
    client = _patch_httpx(monkeypatch, _default_routes())
    cfg = _cfg(client_secret="")

    assert cfg.is_configured is False
    assert is_available(cfg) is False
    assert asyncio.run(fetch_item_picture(cfg, "Naturespan", "SKU-1")) is None
    assert client.calls == []


def test_disable_flag_makes_no_http_call(monkeypatch):
    client = _patch_httpx(monkeypatch, _default_routes())

    assert asyncio.run(fetch_item_picture(_cfg(enabled=False), "Naturespan", "S")) is None
    assert client.calls == []


def test_server_error_returns_none_and_does_not_raise(monkeypatch):
    routes = _default_routes()
    routes["/companies"] = FakeResponse(500, {"error": "boom"})
    _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None


def test_transport_error_returns_none_and_does_not_raise(monkeypatch):
    def _explode(url, kwargs):
        raise bc_api.httpx.ConnectError("no route to host")

    routes = _default_routes()
    routes["/companies"] = _explode
    _patch_httpx(monkeypatch, routes)

    assert asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1")) is None


def test_auth_rejection_trips_breaker_so_a_bulk_sync_calls_once(monkeypatch):
    """401 is today's real state — 600 products must not mean 600 doomed calls."""
    routes = _default_routes()
    routes["/companies"] = FakeResponse(
        401, {"error": {"code": "Authentication_InvalidCredentials"}}
    )
    client = _patch_httpx(monkeypatch, routes)
    cfg = _cfg()

    async def _run():
        return [await fetch_item_picture(cfg, "Naturespan", f"SKU-{i}") for i in range(5)]

    assert asyncio.run(_run()) == [None] * 5
    assert is_available(cfg) is False
    # One token + one rejected companies call, then the breaker holds.
    assert len([u for _, u in client.calls if "/companies" in u]) == 1


def test_throttling_is_retried_with_retry_after(monkeypatch):
    routes = _default_routes()
    routes["/companies"] = [
        FakeResponse(429, {"error": "throttled"}, headers={"Retry-After": "0"}),
        FakeResponse(200, {"value": [{"id": COMPANY_ID, "name": "Naturespan"}]}),
    ]
    client = _patch_httpx(monkeypatch, routes)

    pic = asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1"))

    assert pic is not None
    assert len([u for _, u in client.calls if u.endswith("/companies")]) == 2


def test_company_and_item_lookups_are_cached_across_skus(monkeypatch):
    routes = _default_routes()
    client = _patch_httpx(monkeypatch, routes)
    cfg = _cfg()

    async def _run():
        await fetch_item_picture(cfg, "Naturespan", "SKU-1")
        await fetch_item_picture(cfg, "Naturespan", "SKU-1")

    asyncio.run(_run())

    # Company list and item id resolved once; only the token is reused too.
    assert len([u for _, u in client.calls if u.endswith("/companies")]) == 1
    assert len([u for _, u in client.calls if "/items?" in u]) == 1
    assert len([u for _, u in client.calls if "login.microsoftonline.com" in u]) == 1


def test_media_read_link_accepts_legacy_content_property(monkeypatch):
    """v2.0 names the stream pictureContent; older payloads say content."""
    link = (
        f"https://api.businesscentral.dynamics.com/v2.0/{TENANT}/Production"
        f"/api/v2.0/companies({COMPANY_ID})/items({ITEM_ID})"
        f"/picture({ITEM_ID})/pictureContent"
    )
    routes = _default_routes(
        picture_json={
            "id": ITEM_ID,
            "width": 500,
            "height": 496,
            "contentType": "image/png",
            "content@odata.mediaReadLink": link,
        }
    )
    _patch_httpx(monkeypatch, routes)

    pic = asyncio.run(fetch_item_picture(_cfg(), "Naturespan", "SKU-1"))
    assert pic is not None
    assert pic.content_type == "image/png"
    assert pic.extension == "png"


# ── bc_images: the agents glue ───────────────────────────────────────────


def test_glue_uploads_to_minio_and_returns_object_path(monkeypatch):
    _patch_httpx(monkeypatch, _default_routes())
    monkeypatch.setattr(
        bc_images, "build_bc_config", lambda: _cfg()
    )

    async def _fake_lookup(sku):
        return {"id": "aaaaaaaa-0000-0000-0000-000000000001", "bc_company": "Naturespan"}

    monkeypatch.setattr(bc_images, "_lookup_product", _fake_lookup)

    uploaded = {}

    async def _fake_upload(bucket, object_name, data, content_type):
        uploaded.update(
            bucket=bucket, object_name=object_name, data=data, content_type=content_type
        )
        return object_name

    import shared.tools.storage as storage

    monkeypatch.setattr(storage, "async_upload_file", _fake_upload)

    path = asyncio.run(bc_images.get_product_image_from_bc("SKU-1"))

    assert path == "products/aaaaaaaa-0000-0000-0000-000000000001/gallery/bc_SKU-1.jpg"
    assert uploaded["data"] == JPEG
    assert uploaded["content_type"] == "image/jpeg"
    # Object names must never embed the bucket (see test_storage_paths.py).
    assert not uploaded["object_name"].startswith(uploaded["bucket"])


def test_glue_returns_none_when_product_has_no_bc_company(monkeypatch):
    client = _patch_httpx(monkeypatch, _default_routes())
    monkeypatch.setattr(bc_images, "build_bc_config", lambda: _cfg())

    async def _fake_lookup(sku):
        return {"id": "x", "bc_company": None, "brand_bc_company": None}

    monkeypatch.setattr(bc_images, "_lookup_product", _fake_lookup)

    assert asyncio.run(bc_images.get_product_image_from_bc("SKU-1")) is None
    assert client.calls == []


def test_glue_survives_a_database_failure(monkeypatch):
    _patch_httpx(monkeypatch, _default_routes())
    monkeypatch.setattr(bc_images, "build_bc_config", lambda: _cfg())

    async def _boom(sku):
        raise RuntimeError("db down")

    monkeypatch.setattr(bc_images, "_lookup_product", _boom)

    assert asyncio.run(bc_images.get_product_image_from_bc("SKU-1")) is None


def test_glue_sku_is_path_sanitised(monkeypatch):
    assert bc_images._safe_segment("A/B..C") == "A-B-C"
    assert bc_images._safe_segment("NS/100.2") == "NS-100-2"
    assert bc_images._safe_segment("") == "unknown"
    # No '..' can survive, so a BC item number can never escape the prefix.
    assert bc_images._safe_segment("../../etc/passwd") == "etc-passwd"


# ── the sourcing chain order ─────────────────────────────────────────────


def _chain(monkeypatch, *, bc, supplier=None, web=None):
    """Patch the three sourcing steps and record which ones ran."""
    from workflows.content import image_sourcing

    called = []

    async def _bc(sku, bc_company=None, product_id=None):
        called.append("bc")
        if isinstance(bc, Exception):
            raise bc
        return bc

    async def _supplier(url):
        called.append("supplier")
        return supplier or []

    async def _web(product_name, supplier_url=None, brand=""):
        called.append("web")
        return web

    monkeypatch.setattr(image_sourcing, "get_product_image_from_bc", _bc)
    monkeypatch.setattr(image_sourcing, "scrape_product_images", _supplier)
    monkeypatch.setattr(image_sourcing, "find_product_image", _web)
    return image_sourcing, called


def test_bc_hit_short_circuits_the_chain(monkeypatch):
    chain, called = _chain(monkeypatch, bc="products/p1/gallery/bc_SKU-1.jpg")

    result = asyncio.run(
        chain.source_product_image(
            product_sku="SKU-1",
            product_name="Hemp Flour 250g",
            supplier_url="https://supplier.example/p",
            brand_name="Naturespan",
        )
    )

    assert result.source == "bc"
    assert result.image_url == "products/p1/gallery/bc_SKU-1.jpg"
    assert result.confidence == 1.0
    assert result.needs_manual is False
    # Neither the supplier scrape nor web search ran.
    assert called == ["bc"]


def test_bc_miss_falls_through_to_supplier_then_web(monkeypatch):
    chain, called = _chain(
        monkeypatch, bc=None, supplier=["https://supplier.example/img.jpg"]
    )

    result = asyncio.run(
        chain.source_product_image(
            product_sku="SKU-1",
            product_name="Hemp Flour 250g",
            supplier_url="https://supplier.example/p",
        )
    )

    assert result.source == "supplier"
    assert called == ["bc", "supplier"]


def test_bc_and_supplier_miss_falls_through_to_web(monkeypatch):
    class _Web:
        url = "https://images.example/x.jpg"
        source = "web_search"
        confidence = 0.6

    chain, called = _chain(monkeypatch, bc=None, supplier=[], web=_Web())

    result = asyncio.run(
        chain.source_product_image(
            product_sku="SKU-1",
            product_name="Hemp Flour 250g",
            supplier_url="https://supplier.example/p",
        )
    )

    assert result.source == "web_search"
    assert called == ["bc", "supplier", "web"]


def test_bc_error_falls_through_and_does_not_raise(monkeypatch):
    chain, called = _chain(
        monkeypatch,
        bc=RuntimeError("BC exploded"),
        supplier=["https://supplier.example/img.jpg"],
    )

    result = asyncio.run(
        chain.source_product_image(
            product_sku="SKU-1",
            product_name="Hemp Flour 250g",
            supplier_url="https://supplier.example/p",
        )
    )

    assert result.source == "supplier"
    assert called == ["bc", "supplier"]


def test_nothing_found_flags_manual(monkeypatch):
    chain, called = _chain(monkeypatch, bc=None, supplier=[], web=None)

    result = asyncio.run(
        chain.source_product_image(product_sku="SKU-1", product_name="Hemp Flour")
    )

    assert result.needs_manual is True
    assert result.image_url is None


def test_fabric_import_site_still_works(monkeypatch):
    """image_sourcing imports from shared.tools.fabric — keep that alive."""
    from shared.tools.fabric import get_product_image_from_bc

    async def _fake(sku, bc_company=None, product_id=None):
        return f"products/p/gallery/bc_{sku}.jpg"

    monkeypatch.setattr(bc_images, "get_product_image_from_bc", _fake)
    assert asyncio.run(get_product_image_from_bc("SKU-9")) == (
        "products/p/gallery/bc_SKU-9.jpg"
    )


# ── the vendored copy must not drift ─────────────────────────────────────


def test_bc_api_is_byte_identical_to_the_backend_copy():
    """One implementation, two Docker build contexts.

    agents/ and backend/ are built from disjoint contexts so the protocol file
    is vendored rather than imported. This test is what stops the two copies
    from forking — edit agents/shared/tools/bc_api.py and copy it across.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    mine = os.path.join(here, "..", "shared", "tools", "bc_api.py")
    theirs = os.path.join(here, "..", "..", "backend", "app", "services", "bc_api.py")
    if not os.path.exists(theirs):
        pytest.skip("backend tree not present (running inside the agents container)")
    with open(mine, "rb") as fh:
        a = fh.read()
    with open(theirs, "rb") as fh:
        b = fh.read()
    assert a == b, (
        "bc_api.py has drifted between agents/ and backend/. "
        "Edit agents/shared/tools/bc_api.py and copy it to "
        "backend/app/services/bc_api.py."
    )
