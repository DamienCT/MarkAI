"""Proxy endpoint for serving MinIO files to the browser.

MinIO is internal (minio:9000) and not reachable from the public internet.
This endpoint streams files through the backend so the browser can load
images without mixed-content or DNS resolution issues.

Supports optional ?w=WIDTH&q=QUALITY query params for on-the-fly thumbnail
generation (preview quality). Full-size originals are served by default.

Video files (mp4/webm/mov) are streamed straight from MinIO with HTTP Range
support (206 Partial Content) so browsers can scrub without downloading the
whole file — the object is never buffered in backend memory.
"""

import asyncio
import io
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.services import minio_service

logger = logging.getLogger(__name__)

router = APIRouter()

KNOWN_BUCKETS = {"content-images", "brand-assets", "markai-assets", "products", "videos"}

# Path prefixes that live inside the default bucket (not separate buckets)
_DEFAULT_BUCKET_PREFIXES = {"products", "brands", "screenshots", "contents"}

# Image extensions that support resizing
_RESIZABLE_EXTS = {"png", "jpg", "jpeg", "webp"}

# Video extensions served via Range-capable streaming
_VIDEO_EXTS = {"mp4", "webm", "mov"}

_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
}

# Allowed resize widths — requested widths are snapped up to the nearest entry
# so a public caller can't force arbitrary-size Pillow work per request.
_ALLOWED_WIDTHS = (64, 128, 256, 400, 512, 640, 800, 1024, 1280, 1600, 2048)

# Chunk size for streaming video bytes out of MinIO
_STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def parse_range_header(range_header: str, file_size: int) -> Optional[tuple[int, int]]:
    """Parse a single-range ``Range: bytes=start-end`` header.

    Returns inclusive ``(start, end)`` byte offsets clamped to *file_size*,
    or ``None`` when the header is malformed or unsatisfiable (the caller
    should respond 416). Multi-range requests are not supported.

    Pure function — no I/O — so it can be unit-tested without MinIO.
    """
    if file_size <= 0 or not range_header:
        return None
    header = range_header.strip().lower()
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].strip()
    if "," in spec:
        return None  # multi-range not supported
    start_s, sep, end_s = spec.partition("-")
    if not sep:
        return None
    start_s = start_s.strip()
    end_s = end_s.strip()
    try:
        if not start_s:
            # Suffix range: last N bytes (bytes=-500)
            if not end_s:
                return None
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(file_size - suffix, 0)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or start >= file_size or start > end:
        return None
    return start, min(end, file_size - 1)


def _stream_minio_object(bucket: str, object_name: str, offset: int = 0, length: int = 0):
    """Yield chunks of a MinIO object without buffering it fully in memory.

    Sync generator — Starlette's StreamingResponse iterates it in a
    threadpool, so the blocking reads don't stall the event loop.
    """
    client = minio_service.get_client()
    response = client.get_object(bucket, object_name, offset=offset, length=length)
    try:
        for chunk in response.stream(_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        response.close()
        response.release_conn()


async def _serve_video(request: Request, bucket: str, object_name: str, media_type: str):
    """Stream a video from MinIO, honoring single-range Range requests."""
    client = minio_service.get_client()
    try:
        stat = await asyncio.to_thread(client.stat_object, bucket, object_name)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")
    file_size = stat.size or 0

    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
    }

    range_header = request.headers.get("range")
    if range_header and range_header.strip().lower().startswith("bytes="):
        byte_range = parse_range_header(range_header, file_size)
        if byte_range is None:
            raise HTTPException(
                status_code=416,
                detail="Range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start, end = byte_range
        length = end - start + 1
        return StreamingResponse(
            _stream_minio_object(bucket, object_name, offset=start, length=length),
            status_code=206,
            media_type=media_type,
            headers={
                **common_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
            },
        )

    # Non-Range request (or a range unit we don't understand, which the RFC
    # says to ignore): stream the full object with Accept-Ranges advertised.
    return StreamingResponse(
        _stream_minio_object(bucket, object_name),
        media_type=media_type,
        headers={**common_headers, "Content-Length": str(file_size)},
    )


@router.get("/{file_path:path}")
async def serve_file(
    request: Request,
    file_path: str,
    w: Optional[int] = Query(None, ge=16, le=2048, description="Resize width"),
    q: Optional[int] = Query(None, ge=10, le=100, description="JPEG quality"),
    fmt: Optional[str] = Query(None, description="Force output format, e.g. 'jpg'"),
):
    """Proxy a file from MinIO to the browser.

    Public endpoint — files are behind unguessable UUID paths.
    Content images, brand assets, and mockups need to load in <img> tags
    which cannot send Authorization headers.

    Optional query params for preview thumbnails:
      ?w=400    — resize to 400px wide (maintains aspect ratio)
      ?q=70     — JPEG quality (default 80, only applies when resizing)

    Videos are streamed with HTTP Range support; resize params are ignored.
    """
    # Block path traversal attempts (including backslash variants) and
    # control characters / null bytes in the object path.
    if (
        ".." in file_path
        or file_path.startswith("/")
        or "\\" in file_path
        or any(ord(c) < 32 for c in file_path)
    ):
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

    # Determine content type from extension
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    ct = _CONTENT_TYPES.get(ext, "application/octet-stream")

    # Videos: stream from MinIO with Range support — never buffered in memory
    if ext in _VIDEO_EXTS:
        return await _serve_video(request, bucket, object_name, ct)

    try:
        data = await minio_service.download_file(object_name, bucket=bucket)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    # On-the-fly transform:
    #   ?w=WIDTH  → resize (preview thumbnail)
    #   ?fmt=jpg  → convert to JPEG (Instagram's API only accepts JPEG, not PNG)
    want_jpeg = fmt in ("jpg", "jpeg")
    if (w or want_jpeg) and ext in _RESIZABLE_EXTS:
        if w:
            # Snap to the nearest allowed width so callers can't request
            # arbitrary resize dimensions (Query bounds reject >2048).
            w = min((aw for aw in _ALLOWED_WIDTHS if aw >= w), default=_ALLOWED_WIDTHS[-1])
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            if w:
                ratio = w / img.width
                new_h = int(img.height * ratio)
                img = img.resize((w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            quality = q or (90 if want_jpeg else 80)
            if want_jpeg or ext in ("jpg", "jpeg") or ext == "png":
                img.convert("RGB").save(buf, format="JPEG", quality=quality)
                ct = "image/jpeg"
            elif ext == "webp":
                img.save(buf, format="WEBP", quality=quality)
            data = buf.getvalue()
        except Exception:
            pass  # Serve original if transform fails

    return Response(
        content=data,
        media_type=ct,
        headers={"Cache-Control": "public, max-age=3600"},
    )
