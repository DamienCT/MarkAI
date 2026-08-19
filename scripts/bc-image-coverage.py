#!/usr/bin/env python3
"""Report how many active products have a Business Central item-card picture.

READ-ONLY. Queries the products table, then asks the BC API v2.0 whether each
item No. has a picture on its item card. Writes nothing to the database, MinIO
or Business Central, and publishes/schedules/approves nothing.

Run it inside the agents container so it picks up the real credentials:

    scp scripts/bc-image-coverage.py markai:/tmp/
    ssh markai 'docker cp /tmp/bc-image-coverage.py markai-agents:/tmp/ \
        && docker exec markai-agents python /tmp/bc-image-coverage.py'

If BC access has not been granted yet, the run stops after a single rejected
call (the auth circuit breaker in shared/tools/bc_api.py) and prints the exact
grant that is missing. See AUDIT_ARTIFACTS/bc_image_coverage.md.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "/app")

from shared.tools.bc_api import fetch_item_picture, is_available  # noqa: E402
from shared.tools.bc_images import build_bc_config  # noqa: E402
from shared.tools.database import execute_query  # noqa: E402


def _gallery_sources(row: dict) -> str:
    gallery = row.get("image_urls")
    if isinstance(gallery, str):
        try:
            gallery = json.loads(gallery)
        except Exception:
            gallery = []
    if isinstance(gallery, dict):
        gallery = list(gallery.values())
    sources = {
        entry["source"]
        for entry in (gallery or [])
        if isinstance(entry, dict) and entry.get("source")
    }
    if sources:
        return ",".join(sorted(sources))
    return "unknown" if row.get("primary_image_url") else "none"


async def main() -> int:
    rows = await execute_query(
        "SELECT p.id, p.bc_item_no, p.sku, p.name, p.bc_company, "
        "       p.primary_image_url, p.image_urls, b.name AS brand_name "
        "FROM products p LEFT JOIN brands b ON b.id = p.brand_id "
        "WHERE p.is_active = true "
        "ORDER BY p.bc_company, p.bc_item_no",
        {},
    )
    print(f"Active products: {len(rows)}")

    by_company: dict[str, list[dict]] = {}
    for row in rows:
        by_company.setdefault(row.get("bc_company") or "<none>", []).append(row)

    print("\nBy BC company:")
    for company, items in sorted(by_company.items()):
        with_no = sum(1 for i in items if (i.get("bc_item_no") or i.get("sku")))
        with_img = sum(1 for i in items if i.get("primary_image_url"))
        print(
            f"  {company}: {len(items)} active | {with_no} with an item No. | "
            f"{with_img} already have an image"
        )

    counts: dict[str, int] = {}
    for row in rows:
        key = _gallery_sources(row)
        counts[key] = counts.get(key, 0) + 1
    print("\nCurrent image sources:")
    for source, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {source}: {n}")

    cfg = build_bc_config()
    print(
        f"\nBC configured={cfg.is_configured} available={is_available(cfg)} "
        f"environment={cfg.environment}"
    )
    if not is_available(cfg):
        print("\nBC probe SKIPPED — no API access. See the grant steps in")
        print("AUDIT_ARTIFACTS/bc_image_coverage.md.")
        return 1

    hits: list[dict] = []
    misses: list[dict] = []
    for row in rows:
        sku = (row.get("bc_item_no") or row.get("sku") or "").strip()
        company = (row.get("bc_company") or "").strip()
        if not sku or not company:
            continue
        picture = await fetch_item_picture(cfg, company, sku)
        record = {
            "company": company,
            "sku": sku,
            "name": row.get("name"),
            "brand": row.get("brand_name"),
            "current_source": _gallery_sources(row),
        }
        if picture is not None:
            record["bytes"] = len(picture.content)
            record["content_type"] = picture.content_type
            hits.append(record)
        else:
            misses.append(record)
        if not is_available(cfg):
            print("\nAborted — BC access was lost mid-run.")
            break

    print(f"\nBC item-card pictures available: {len(hits)} / {len(hits) + len(misses)}")
    print("\nProducts WITH a BC picture:")
    for record in hits:
        print(
            f"  {record['company']}/{record['sku']} — {record['name']} "
            f"({record['bytes']} bytes, currently {record['current_source']})"
        )
    print("\nProducts WITHOUT a BC picture:")
    for record in misses:
        print(f"  {record['company']}/{record['sku']} — {record['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
