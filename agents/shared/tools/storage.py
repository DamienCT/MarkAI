"""Real MinIO / S3-compatible object storage client."""

from __future__ import annotations

import io
import logging
from datetime import timedelta

from minio import Minio

from shared.config import settings

logger = logging.getLogger(__name__)

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


def ensure_bucket(bucket_name: str) -> None:
    """Create the bucket if it does not already exist."""
    client = _get_client()
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        logger.info("Created bucket %s", bucket_name)


def upload_file(
    bucket: str,
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload *data* to MinIO and return the object name."""
    ensure_bucket(bucket)
    client = _get_client()
    client.put_object(
        bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    logger.info("Uploaded %s/%s (%d bytes)", bucket, object_name, len(data))
    return object_name


def download_file(bucket: str, object_name: str) -> bytes:
    """Download an object from MinIO and return its bytes."""
    client = _get_client()
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def get_presigned_url(
    bucket: str,
    object_name: str,
    expires: timedelta = timedelta(hours=1),
) -> str:
    """Return a presigned GET URL valid for *expires*."""
    client = _get_client()
    return client.presigned_get_object(bucket, object_name, expires=expires)
