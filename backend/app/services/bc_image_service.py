"""Backend glue for Business Central item-card pictures.

The BC protocol itself lives in :mod:`app.services.bc_api`, which is the same
file as ``agents/shared/tools/bc_api.py`` (vendored byte-identically because
the two services are built from disjoint Docker contexts; a drift test in each
suite fails if they diverge). This module only wires it to the backend runtime:
settings -> :class:`BCConfig`, ``Product`` row -> BC company + SKU.

It returns the same dict shape as ``_fetch_one_product_image_via_worker`` in
``app.api.v1.products`` so both sources drop into ``_save_image_to_gallery``
unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.bc_api import BCConfig, fetch_item_picture, is_available, probe

logger = logging.getLogger(__name__)


def build_bc_config() -> BCConfig:
    """Build the BC API config from settings.

    The dedicated ``BC_API_*`` settings win; each falls back to the Fabric
    service-principal values, because in this tenant the same Entra app is
    intended to carry both the Fabric SQL and the BC API grant.
    """
    return BCConfig(
        tenant_id=getattr(settings, "BC_API_TENANT_ID", "")
        or getattr(settings, "FABRIC_TENANT_ID", ""),
        client_id=getattr(settings, "BC_API_CLIENT_ID", "")
        or getattr(settings, "FABRIC_CLIENT_ID", ""),
        client_secret=getattr(settings, "BC_API_CLIENT_SECRET", "")
        or getattr(settings, "FABRIC_CLIENT_SECRET", ""),
        environment=getattr(settings, "BC_API_ENVIRONMENT", "") or "Production",
        base_url=getattr(settings, "BC_API_BASE_URL", "")
        or "https://api.businesscentral.dynamics.com",
        enabled=bool(getattr(settings, "BC_API_ENABLED", True)),
    )


def bc_company_for(product: Any) -> str:
    """The BC company a product belongs to (its own value, else its brand's).

    BC-synced products always carry ``bc_company``; the brand fallback is for
    hand-created rows. It is guarded because ``Product.brand`` is a lazy
    relationship — touching it on a product loaded without an eager join
    raises ``MissingGreenlet`` under asyncio.
    """
    company = (getattr(product, "bc_company", None) or "").strip()
    if company:
        return company
    try:
        brand = getattr(product, "brand", None)
        return ((getattr(brand, "bc_company", None) or "") if brand else "").strip()
    except Exception:
        return ""


def bc_sku_for(product: Any) -> str:
    """The BC item No. for a product (``bc_item_no`` is the BC key; sku is a fallback)."""
    return (
        (getattr(product, "bc_item_no", None) or "")
        or (getattr(product, "sku", None) or "")
    ).strip()


def has_bc_image(product: Any) -> bool:
    """True when the gallery already holds a BC item-card picture.

    Short-circuits the API call so a 600-product sync doesn't re-download
    pictures it already has.
    """
    gallery = getattr(product, "image_urls", None)
    if isinstance(gallery, dict):
        gallery = list(gallery.values())
    if not isinstance(gallery, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("source") == "business_central"
        for entry in gallery
    )


async def fetch_product_image_from_bc(product: Any) -> dict[str, Any] | None:
    """Fetch the item-card picture for a product, ready for the gallery.

    Returns ``{"url", "content_type", "size_bytes", "image_data", "source"}``
    or ``None``. Never raises: BC being down or unauthorised must degrade to
    the supplier/web-search path, not fail the request.

    NOTE: the caller deliberately does NOT run the ``_image_depicts_product``
    vision gate on this result. That gate exists because web image search
    matches on brand + keywords and happily returns a different item from the
    same maker. A BC item-card picture is authoritative — it is the photo the
    client attached to that exact item No. in their own ERP — so there is
    nothing to second-guess, and a vision false-negative would throw away the
    single most trustworthy image we have.
    """
    cfg = build_bc_config()
    if not is_available(cfg):
        return None

    sku = bc_sku_for(product)
    company = bc_company_for(product)
    if not sku or not company:
        logger.debug(
            "Skipping BC image for product %s — missing %s",
            getattr(product, "id", "?"),
            "SKU" if not sku else "BC company",
        )
        return None

    picture = await fetch_item_picture(cfg, company, sku)
    if picture is None:
        return None

    return {
        "url": f"bc://{company}/items/{sku}",
        "content_type": picture.content_type,
        "size_bytes": len(picture.content),
        "image_data": picture.content,
        "source": "business_central",
        "bc_company": company,
        "bc_item_no": sku,
        "extension": picture.extension,
    }


async def probe_bc_access() -> dict[str, Any]:
    """Diagnostic passthrough — reports reachability without exposing secrets."""
    return await probe(build_bc_config())
