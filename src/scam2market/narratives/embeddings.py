import hashlib
import math
import re
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]+")


class EmbeddingProvider(Protocol):
    version: str
    dimensions: int

    async def embed(self, text: str) -> list[float]: ...


class VectorIndex(Protocol):
    async def upsert(
        self, point_id: str, vector: list[float], metadata: dict[str, Any]
    ) -> None: ...

    async def query(
        self, vector: list[float], *, limit: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]: ...


class DeterministicHashEmbedding:
    version = "hash-embedding-v1"

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + min(len(token), 12) / 12.0)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            return [value / norm for value in vector]
        return vector


class QdrantVectorIndex:
    def __init__(
        self,
        url: str,
        collection_name: str,
        dimensions: int,
    ) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection_name
        self._dimensions = dimensions
        self._ready = False

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._dimensions, distance=models.Distance.COSINE
                ),
            )
        self._ready = True

    async def upsert(self, point_id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        await self.ensure_collection()
        await self._client.upsert(
            collection_name=self._collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload=metadata)],
            wait=True,
        )

    async def query(
        self, vector: list[float], *, limit: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        await self.ensure_collection()
        response = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        return [
            (str(point.id), float(point.score), dict(point.payload or {}))
            for point in response.points
        ]

    async def close(self) -> None:
        await self._client.close()


class InMemoryVectorIndex:
    def __init__(self) -> None:
        self.points: dict[str, tuple[list[float], dict[str, Any]]] = {}

    async def upsert(self, point_id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        self.points[point_id] = (list(vector), dict(metadata))

    async def query(
        self, vector: list[float], *, limit: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        ranked = sorted(
            (
                (point_id, cosine_similarity(vector, candidate), metadata)
                for point_id, (candidate, metadata) in self.points.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(
        0.0,
        min(
            1.0,
            sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm),
        ),
    )
