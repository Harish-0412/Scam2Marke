from collections.abc import Mapping
from typing import Any, Protocol

import orjson
from redis.asyncio import Redis


class DedupeStore(Protocol):
    async def claim(self, key: str, ttl_seconds: int = 86_400) -> bool: ...

    async def release(self, key: str) -> None: ...


class OnlineStateStore(Protocol):
    async def set_json(self, key: str, value: Mapping[str, Any]) -> None: ...

    async def get_json(self, key: str) -> dict[str, Any] | None: ...


class RedisStateStore(DedupeStore, OnlineStateStore):
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=False)

    async def claim(self, key: str, ttl_seconds: int = 86_400) -> bool:
        result = await self._redis.set(f"dedupe:{key}", b"1", ex=ttl_seconds, nx=True)
        return bool(result)

    async def set_json(self, key: str, value: Mapping[str, Any]) -> None:
        await self._redis.set(key, orjson.dumps(value))

    async def release(self, key: str) -> None:
        await self._redis.delete(f"dedupe:{key}")

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = await self._redis.get(key)
        if value is None:
            return None
        decoded: object = orjson.loads(value)
        if not isinstance(decoded, dict):
            raise TypeError(f"online state at {key!r} is not an object")
        return {str(key): item for key, item in decoded.items()}

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryStateStore(DedupeStore, OnlineStateStore):
    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.values: dict[str, dict[str, Any]] = {}

    async def claim(self, key: str, ttl_seconds: int = 86_400) -> bool:
        del ttl_seconds
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def set_json(self, key: str, value: Mapping[str, Any]) -> None:
        self.values[key] = dict(value)

    async def release(self, key: str) -> None:
        self.claimed.discard(key)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = self.values.get(key)
        return dict(value) if value is not None else None
