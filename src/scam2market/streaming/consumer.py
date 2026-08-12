import ssl
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import orjson
from aiokafka import AIOKafkaConsumer, TopicPartition

from scam2market.config.settings import get_settings
from scam2market.schemas.events import CanonicalEvent


@dataclass(frozen=True, slots=True)
class ConsumedEvent:
    event: CanonicalEvent
    topic: str
    partition: int
    offset: int


class EventConsumer:
    def __init__(
        self,
        topics: Sequence[str],
        *,
        group_id: str,
        bootstrap_servers: str | None = None,
    ) -> None:
        settings = get_settings()
        ssl_context = (
            ssl.create_default_context() if settings.kafka_security_protocol == "SSL" else None
        )
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers or settings.redpanda_bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            isolation_level="read_committed",
            value_deserializer=orjson.loads,
            security_protocol=settings.kafka_security_protocol,
            ssl_context=ssl_context,
        )

    async def __aenter__(self) -> "EventConsumer":
        await self._consumer.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._consumer.stop()

    async def events(self) -> AsyncIterator[CanonicalEvent]:
        async for record in self.records():
            yield record.event

    async def records(self) -> AsyncIterator[ConsumedEvent]:
        async for message in self._consumer:
            yield ConsumedEvent(
                event=CanonicalEvent.model_validate(message.value),
                topic=message.topic,
                partition=message.partition,
                offset=message.offset,
            )

    async def batches(self) -> AsyncIterator[list[ConsumedEvent]]:
        settings = get_settings()
        timeout_ms = max(1, int(settings.stream_batch_wait_seconds * 1000))
        while True:
            records = await self._consumer.getmany(
                timeout_ms=timeout_ms,
                max_records=settings.stream_batch_size,
            )
            batch = [
                ConsumedEvent(
                    event=CanonicalEvent.model_validate(message.value),
                    topic=message.topic,
                    partition=message.partition,
                    offset=message.offset,
                )
                for _, messages in records.items()
                for message in messages
            ]
            if batch:
                yield sorted(
                    batch,
                    key=lambda item: (
                        item.event.event_time,
                        item.topic,
                        item.partition,
                        item.offset,
                    ),
                )

    async def commit(self, record: ConsumedEvent | None = None) -> None:
        if record is None:
            await self._consumer.commit()
            return
        partition = TopicPartition(record.topic, record.partition)
        await self._consumer.commit({partition: record.offset + 1})
