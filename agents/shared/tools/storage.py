"""Real MinIO / S3-compatible object storage client."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

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
        try:
            client.make_bucket(bucket_name)
            logger.info("Created bucket %s", bucket_name)
        except S3Error as exc:
            # Another worker may have created the bucket concurrently
            if (
                exc.code == "BucketAlreadyOwnedByYou"
                or exc.code == "BucketAlreadyExists"
            ):
                logger.debug(
                    "Bucket %s already exists (race condition handled)", bucket_name
                )
            else:
                raise


def upload_file(
    bucket: str,
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload *data* to MinIO and return the object name (sync)."""
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


async def async_upload_file(
    bucket: str,
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload *data* to MinIO in a thread (non-blocking for async callers)."""
    return await asyncio.to_thread(upload_file, bucket, object_name, data, content_type)


def download_file(bucket: str, object_name: str) -> bytes:
    """Download an object from MinIO and return its bytes (sync)."""
    client = _get_client()
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def async_download_file(bucket: str, object_name: str) -> bytes:
    """Download an object from MinIO in a thread (non-blocking for async callers)."""
    return await asyncio.to_thread(download_file, bucket, object_name)


def get_presigned_url(
    bucket: str,
    object_name: str,
    expires: timedelta = timedelta(hours=1),
) -> str:
    """Return a presigned GET URL valid for *expires* (sync)."""
    client = _get_client()
    return client.presigned_get_object(bucket, object_name, expires=expires)


async def async_get_presigned_url(
    bucket: str,
    object_name: str,
    expires: timedelta = timedelta(hours=1),
) -> str:
    """Return a presigned GET URL in a thread (non-blocking for async callers)."""
    return await asyncio.to_thread(get_presigned_url, bucket, object_name, expires)


async def async_ensure_bucket(bucket_name: str) -> None:
    """Create the bucket if it does not already exist (non-blocking)."""
    await asyncio.to_thread(ensure_bucket, bucket_name)
