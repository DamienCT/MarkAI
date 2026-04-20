"""Proxy endpoint for serving MinIO files to the browser.

MinIO is internal (minio:9000) and not reachable from the public internet.
This endpoint streams files through the backend so the browser can load
images without mixed-content or DNS resolution issues.

Supports optional ?w=WIDTH&q=QUALITY query params for on-the-fly thumbnail
generation (preview quality). Full-size originals are served by default.
"""

import io
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.config import settings
from app.services import minio_service

logger = logging.getLogger(__name__)

router = APIRouter()

KNOWN_BUCKETS = {"content-images", "brand-assets", "markai-assets", "products"}

# Path prefixes that live inside the default bucket (not separate buckets)
_DEFAULT_BUCKET_PREFIXES = {"products", "brands", "screenshots", "contents"}

# Image extensions that support resizing
_RESIZABLE_EXTS = {"png", "jpg", "jpeg", "webp"}


@router.get("/{file_path:path}")
async def serve_file(
    file_path: str,
    w: Optional[int] = Query(None, ge=16, le=2000, description="Resize width"),
    q: Optional[int] = Query(None, ge=10, le=100, description="JPEG quality"),
):
    """Proxy a file from MinIO to the browser.

    Public endpoint — files are behind unguessable UUID paths.
    Content images, brand assets, and mockups need to load in <img> tags
    which cannot send Authorization headers.

    Optional query params for preview thumbnails:
      ?w=400    — resize to 400px wide (maintains aspect ratio)
      ?q=70     — JPEG quality (default 80, only applies when resizing)
    """
    # Block path traversal attempts (including backslash variants)
    if ".." in file_path or file_path.startswith("/") or "\\" in file_path:
        raise HTTPException(status_code=403, detail="Invalid file path")

    first_segment = file_path.split("/")[0] if "/" in file_path else ""

    if first_segment in _DEFAULT_BUCKET_PREFIXES:
        bucket = settings.MINIO_BUCKET
        object_name = file_path
    elif first_segment in KNOWN_BUCKETS:
        bucket = first_segment
        object_name = file_path[len(first_segment) + 1 :]
    else:
        raise HTTPException(status_code=404, detail="File not found")

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

    # On-the-fly resize for preview thumbnails
    if w and ext in _RESIZABLE_EXTS:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            ratio = w / img.width
            new_h = int(img.height * ratio)
            img = img.resize((w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            quality = q or 80
            if ext in ("jpg", "jpeg") or ext == "png":
                img.save(buf, format="JPEG", quality=quality)
                ct = "image/jpeg"
            elif ext == "webp":
                img.save(buf, format="WEBP", quality=quality)
            data = buf.getvalue()
        except Exception:
            pass  # Serve original if resize fails

    return Response(
        content=data,
        media_type=ct,
        headers={"Cache-Control": "public, max-age=3600"},
    )
