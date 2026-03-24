import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from app.config import settings

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None

DEFAULT_COLLECTION = "markai_embeddings"
VECTOR_SIZE = 1536  # text-embedding-3-small


def get_client() -> QdrantClient:
    """Return the Qdrant client, creating it lazily."""
    global _client
    if _client is None:
        _client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
    return _client


def ensure_collection(
    collection_name: str = DEFAULT_COLLECTION,
    vector_size: int = VECTOR_SIZE,
) -> None:
    """Create a collection if it doesn't exist."""
    client = get_client()
    collections = client.get_collections().collections
    names = [c.name for c in collections]
    if collection_name not in names:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection: %s", collection_name)


def upsert_vectors(
    vectors: list[dict[str, Any]],
    collection_name: str = DEFAULT_COLLECTION,
) -> None:
    """
    Upsert vectors into Qdrant.
    vectors format: [{"id": "uuid", "vector": [...], "payload": {...}}, ...]
    """
    client = get_client()
    points = [
        PointStruct(
            id=str(v["id"]),
            vector=v["vector"],
            payload=v.get("payload", {}),
        )
        for v in vectors
    ]
    client.upsert(collection_name=collection_name, points=points)
    logger.debug("Upserted %d vectors to %s", len(points), collection_name)


def search_vectors(
    query_vector: list[float],
    *,
    collection_name: str = DEFAULT_COLLECTION,
    limit: int = 10,
    score_threshold: float | None = None,
    filter_conditions: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Search for similar vectors in Qdrant.
    Returns list of results with id, score, and payload.
    """
    client = get_client()

    from qdrant_client.models import Filter, FieldCondition, MatchValue

    qdrant_filter = None
    if filter_conditions:
        must = []
        for key, value in filter_conditions.items():
            must.append(FieldCondition(key=key, match=MatchValue(value=value)))
        qdrant_filter = Filter(must=must)

    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold,
        query_filter=qdrant_filter,
    )

    return [
        {
            "id": str(r.id),
            "score": r.score,
            "payload": r.payload,
        }
        for r in results
    ]


def delete_vectors(
    ids: list[str],
    collection_name: str = DEFAULT_COLLECTION,
) -> None:
    """Delete vectors by ID from Qdrant."""
    client = get_client()
    client.delete(
        collection_name=collection_name,
        points_selector=ids,
    )
    logger.debug("Deleted %d vectors from %s", len(ids), collection_name)
