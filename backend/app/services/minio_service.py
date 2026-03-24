import io
import logging
from datetime import timedelta

from minio import Minio

from app.config import settings

logger = logging.getLogger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    """Return the MinIO client, creating it lazily."""
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False,
        )
    return _client


def ensure_bucket() -> None:
    """Create the default bucket if it doesn't exist."""
    client = get_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
        logger.info("Created MinIO bucket: %s", settings.MINIO_BUCKET)


def upload_file(
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    bucket: str | None = None,
) -> str:
    """
    Upload a file to MinIO. Returns the object name (path).
    """
    client = get_client()
    bucket = bucket or settings.MINIO_BUCKET
    client.put_object(
        bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    logger.info("Uploaded %s to bucket %s", object_name, bucket)
    return object_name


def download_file(
    object_name: str,
    bucket: str | None = None,
) -> bytes:
    """Download a file from MinIO. Returns the raw bytes."""
    client = get_client()
    bucket = bucket or settings.MINIO_BUCKET
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def get_presigned_url(
    object_name: str,
    expires: timedelta = timedelta(hours=1),
    bucket: str | None = None,
) -> str:
    """Generate a presigned GET URL for an object."""
    client = get_client()
    bucket = bucket or settings.MINIO_BUCKET
    return client.presigned_get_object(bucket, object_name, expires=expires)


def get_presigned_upload_url(
    object_name: str,
    expires: timedelta = timedelta(hours=1),
    bucket: str | None = None,
) -> str:
    """Generate a presigned PUT URL for uploading."""
    client = get_client()
    bucket = bucket or settings.MINIO_BUCKET
    return client.presigned_put_object(bucket, object_name, expires=expires)


def delete_file(
    object_name: str,
    bucket: str | None = None,
) -> None:
    """Delete a file from MinIO."""
    client = get_client()
    bucket = bucket or settings.MINIO_BUCKET
    client.remove_object(bucket, object_name)
    logger.info("Deleted %s from bucket %s", object_name, bucket)
