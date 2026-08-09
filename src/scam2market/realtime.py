import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, cast

import orjson
from redis.asyncio import Redis


class RealtimeBroker(Protocol):
    async def publish(self, payload: Mapping[str, Any]) -> str: ...

    def subscribe(self, after_id: str = "$") -> AsyncIterator[tuple[str, dict[str, Any]]]: ...


class RedisRealtimeBroker:
    def __init__(self, redis_url: str, stream_key: str, max_length: int = 10_000) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=False)
        self._stream_key = stream_key
        self._max_length = max_length

    async def publish(self, payload: Mapping[str, Any]) -> str:
        event_id = await self._redis.xadd(
            self._stream_key,
            {b"event": orjson.dumps(payload)},
            maxlen=self._max_length,
            approximate=True,
        )
        return event_id.decode() if isinstance(event_id, bytes) else str(event_id)

    async def subscribe(self, after_id: str = "$") -> AsyncIterator[tuple[str, dict[str, Any]]]:
        cursor = after_id
        while True:
            batches = cast(
                list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]],
                await self._redis.xread({self._stream_key: cursor}, count=100, block=15_000),
            )
            if not batches:
                yield "", {"event_type": "heartbeat"}
                continue
            for _, entries in batches:
                for raw_id, fields in entries:
                    cursor = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                    raw_payload = fields.get(b"event")
                    if raw_payload is None:
                        raise TypeError("realtime stream entry is missing event payload")
                    payload: object = orjson.loads(raw_payload)
                    if not isinstance(payload, dict):
                        raise TypeError("realtime stream event must be an object")
                    yield cursor, {str(key): value for key, value in payload.items()}

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryRealtimeBroker:
    def __init__(self) -> None:
        self.history: list[tuple[str, dict[str, Any]]] = []
        self._subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()

    async def publish(self, payload: Mapping[str, Any]) -> str:
        event_id = f"{len(self.history) + 1}-0"
        item = (event_id, dict(payload))
        self.history.append(item)
        for queue in self._subscribers:
            await queue.put(item)
        return event_id

    async def subscribe(self, after_id: str = "$") -> AsyncIterator[tuple[str, dict[str, Any]]]:
        if after_id != "$":
            for item in self.history:
                if _stream_id(item[0]) > _stream_id(after_id):
                    yield item
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


def _stream_id(value: str) -> tuple[int, int]:
    left, _, right = value.partition("-")
    return int(left or 0), int(right or 0)
