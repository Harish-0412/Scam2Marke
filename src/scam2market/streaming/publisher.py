from typing import Protocol

import orjson
from aiokafka import AIOKafkaProducer

from scam2market.config.settings import get_settings
from scam2market.schemas.events import CanonicalEvent


class CanonicalEventPublisher(Protocol):
    async def publish(self, topic: str, event: CanonicalEvent) -> None: ...


class EventPublisher:
    def __init__(self, bootstrap_servers: str | None = None) -> None:
        settings = get_settings()
        self._bootstrap_servers = bootstrap_servers or settings.redpanda_bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: orjson.dumps(value),
            key_serializer=lambda value: value.encode("utf-8"),
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, event: CanonicalEvent) -> None:
        if self._producer is None:
            raise RuntimeError("publisher has not been started")
        await self._producer.send_and_wait(
            topic,
            event.model_dump(mode="json"),
            key=event.partition_key,
        )


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, CanonicalEvent]] = []

    async def publish(self, topic: str, event: CanonicalEvent) -> None:
        self.events.append((topic, event))
