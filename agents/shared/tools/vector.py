"""Real Qdrant vector database client for similarity search and storage."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)

from shared.config import settings

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY or None,
        )
    return _client


def create_collection(
    collection_name: str,
    vector_size: int = 1536,
    distance: Distance = Distance.COSINE,
) -> None:
    """Create a Qdrant collection if it does not exist."""
    client = _get_client()
    collections = [c.name for c in client.get_collections().collections]
    if collection_name not in collections:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=distance),
        )
        logger.info("Created Qdrant collection %s (dim=%d)", collection_name, vector_size)


def upsert_vectors(
    collection_name: str,
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
    ids: list[str] | None = None,
) -> None:
    """Upsert vectors with their payloads into the collection."""
    client = _get_client()
    if ids is None:
        ids = [str(uuid4()) for _ in vectors]

    points = [
        PointStruct(id=point_id, vector=vector, payload=payload)
        for point_id, vector, payload in zip(ids, vectors, payloads)
    ]
    client.upsert(collection_name=collection_name, points=points)
    logger.info("Upserted %d vectors into %s", len(points), collection_name)


def search_similar(
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
    filter_field: str | None = None,
    filter_value: str | None = None,
) -> list[dict[str, Any]]:
    """Search for similar vectors and return payloads with scores."""
    client = _get_client()

    query_filter = None
    if filter_field and filter_value:
        query_filter = Filter(
            must=[FieldCondition(key=filter_field, match=MatchValue(value=filter_value))]
        )

    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit,
        query_filter=query_filter,
    )

    return [
        {"id": str(hit.id), "score": hit.score, "payload": hit.payload}
        for hit in results
    ]


# ── Async wrappers (non-blocking for async callers) ─────────────────────

async def async_create_collection(
    collection_name: str,
    vector_size: int = 1536,
    distance: Distance = Distance.COSINE,
) -> None:
    await asyncio.to_thread(create_collection, collection_name, vector_size, distance)


async def async_upsert_vectors(
    collection_name: str,
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
    ids: list[str] | None = None,
) -> None:
    await asyncio.to_thread(upsert_vectors, collection_name, vectors, payloads, ids)


async def async_search_similar(
    collection_name: str,
    query_vector: list[float],
    limit: int = 10,
    filter_field: str | None = None,
    filter_value: str | None = None,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        search_similar, collection_name, query_vector, limit, filter_field, filter_value
    )
