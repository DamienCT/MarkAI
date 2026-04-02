"""Proxy endpoint for serving MinIO files to the browser.

MinIO is internal (minio:9000) and not reachable from the public internet.
This endpoint streams files from MinIO through the backend so the browser
can load images without mixed-content or DNS resolution issues.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services import minio_service

logger = logging.getLogger(__name__)

router = APIRouter()

KNOWN_BUCKETS = {"content-images", "brand-assets", "markai-assets", "products"}


@router.get("/{file_path:path}")
async def serve_file(
    file_path: str,
):
    """Proxy a file from MinIO to the browser.

    Public endpoint — files are behind unguessable UUID paths.
    Content images, brand assets, and mockups need to load in <img> tags
    which cannot send Authorization headers.
    """
    # Block path traversal attempts (including backslash variants)
    if ".." in file_path or file_path.startswith("/") or "\\" in file_path:
        raise HTTPException(status_code=403, detail="Invalid file path")

    # Parse bucket from first path segment — reject unknown buckets
    first_segment = file_path.split("/")[0] if "/" in file_path else ""
    if first_segment not in KNOWN_BUCKETS:
        raise HTTPException(status_code=404, detail="File not found")

    bucket = first_segment
    object_name = file_path[len(first_segment) + 1 :]

    if not object_name:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        data = await minio_service.download_file(object_name, bucket=bucket)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    # Determine content type from extension
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    content_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
    }
    ct = content_types.get(ext, "application/octet-stream")

    return Response(
        content=data,
        media_type=ct,
        headers={"Cache-Control": "public, max-age=3600"},
    )
