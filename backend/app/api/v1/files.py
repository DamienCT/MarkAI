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


@router.get("/{file_path:path}")
async def serve_file(
    file_path: str,
):
    """Proxy a file from MinIO to the browser (public — scoped to known object paths)."""
    # Block path traversal attempts
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=403, detail="Invalid file path")
    try:
        data = await minio_service.download_file(file_path)
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
