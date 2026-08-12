import asyncio
import ssl
from collections.abc import Sequence
from typing import Protocol
from uuid import uuid4

import orjson
from aiokafka import AIOKafkaProducer

from scam2market.config.settings import get_settings
from scam2market.schemas.events import CanonicalEvent


class CanonicalEventPublisher(Protocol):
    async def publish(self, topic: str, event: CanonicalEvent) -> None: ...

    async def publish_batch(self, events: Sequence[tuple[str, CanonicalEvent]]) -> None: ...


class EventPublisher:
    def __init__(self, bootstrap_servers: str | None = None) -> None:
        settings = get_settings()
        self._bootstrap_servers = bootstrap_servers or settings.redpanda_bootstrap_servers
        self._security_protocol = settings.kafka_security_protocol
        self._producer: AIOKafkaProducer | None = None
        self._transactional_id = f"scam2market-producer-{uuid4()}"
        self._transaction_lock = asyncio.Lock()

    async def start(self) -> None:
        ssl_context = ssl.create_default_context() if self._security_protocol == "SSL" else None
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: orjson.dumps(value),
            key_serializer=lambda value: value.encode("utf-8"),
            enable_idempotence=True,
            transactional_id=self._transactional_id,
            security_protocol=self._security_protocol,
            ssl_context=ssl_context,
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, event: CanonicalEvent) -> None:
        await self.publish_batch(((topic, event),))

    async def publish_batch(self, events: Sequence[tuple[str, CanonicalEvent]]) -> None:
        if self._producer is None:
            raise RuntimeError("publisher has not been started")
        async with self._transaction_lock, self._producer.transaction():
            for topic, event in events:
                await self._producer.send(
                    topic,
                    event.model_dump(mode="json"),
                    key=event.partition_key,
                )


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, CanonicalEvent]] = []

    async def publish(self, topic: str, event: CanonicalEvent) -> None:
        self.events.append((topic, event))

    async def publish_batch(self, events: Sequence[tuple[str, CanonicalEvent]]) -> None:
        self.events.extend(events)
