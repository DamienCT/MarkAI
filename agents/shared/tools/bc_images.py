"""Agents-side glue for Business Central item-card pictures.

The BC protocol itself lives in :mod:`shared.tools.bc_api` (one implementation,
vendored byte-identically into the backend). This module only wires it to the
agents runtime: settings -> :class:`BCConfig`, SKU -> BC company, picture bytes
-> MinIO object path.

Step 1 of the sourcing chain in ``workflows/content/image_sourcing.py`` calls
this before the supplier-website scrape and long before web search: an image on
the client's own item card is the authoritative product photo.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from shared.config import settings
from shared.tools.bc_api import BCConfig, BCPicture, fetch_item_picture, is_available

logger = logging.getLogger(__name__)

# Dots are NOT safe: they are what makes '..' a traversal segment, and BC item
# numbers routinely contain '/' and '.' (e.g. 'NS/100.2').
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_-]+")


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


def _safe_segment(value: str) -> str:
    """Make an object-path segment out of arbitrary text (SKUs contain '/')."""
    cleaned = _SAFE_SEGMENT_RE.sub("-", (value or "").strip()).strip("-")
    return cleaned[:80] or "unknown"


async def _lookup_product(product_sku: str) -> dict[str, Any] | None:
    """Find the product row for a SKU so we know its BC company and id."""
    from shared.tools.database import execute_query

    rows = await execute_query(
        "SELECT p.id AS id, p.bc_company AS bc_company, b.bc_company AS brand_bc_company "
        "FROM products p LEFT JOIN brands b ON b.id = p.brand_id "
        "WHERE p.bc_item_no = :sku OR p.sku = :sku "
        "ORDER BY p.is_active DESC, p.updated_at DESC LIMIT 1",
        {"sku": product_sku},
    )
    return dict(rows[0]) if rows else None


def _object_path(picture: BCPicture, product_id: str | None, company: str) -> str:
    """Deterministic MinIO key, so re-fetching replaces instead of piling up.

    Matches the ``products/`` prefix the backend gallery already uses
    (``products/{product_id}/gallery/...``).
    """
    sku = _safe_segment(picture.sku)
    if product_id:
        return f"products/{product_id}/gallery/bc_{sku}.{picture.extension}"
    return f"products/bc/{_safe_segment(company)}/{sku}.{picture.extension}"


async def get_product_image_from_bc(
    product_sku: str,
    bc_company: str | None = None,
    product_id: str | None = None,
) -> str | None:
    """Return a MinIO object path for the BC item-card picture, or ``None``.

    ``bc_company``/``product_id`` are optional; when omitted they are resolved
    from the products table by SKU. Returns ``None`` — never raises — when BC
    has no picture, is unconfigured, or errors, so the caller falls through to
    the supplier-website and web-search steps.
    """
    if not product_sku:
        return None

    cfg = build_bc_config()
    if not is_available(cfg):
        return None

    company = bc_company
    pid = product_id
    if not company or not pid:
        try:
            row = await _lookup_product(product_sku)
        except Exception:
            logger.exception("Product lookup failed for SKU %s", product_sku)
            row = None
        if row:
            company = company or row.get("bc_company") or row.get("brand_bc_company")
            pid = pid or (str(row["id"]) if row.get("id") else None)

    if not company:
        logger.debug("No BC company known for SKU %s — skipping BC image", product_sku)
        return None

    picture = await fetch_item_picture(cfg, company, product_sku)
    if picture is None:
        return None

    object_name = _object_path(picture, pid, company)
    try:
        from shared.tools.storage import async_upload_file

        bucket = getattr(settings, "MINIO_BUCKET", "markai-assets")
        await async_upload_file(
            bucket, object_name, picture.content, picture.content_type
        )
    except Exception:
        logger.exception("Failed to store BC picture for %s in MinIO", product_sku)
        return None

    logger.info("Stored BC item-card picture for %s at %s", product_sku, object_name)
    return object_name
