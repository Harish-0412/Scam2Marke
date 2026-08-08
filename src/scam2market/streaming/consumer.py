from collections.abc import AsyncIterator, Sequence

import orjson
from aiokafka import AIOKafkaConsumer

from scam2market.config.settings import get_settings
from scam2market.schemas.events import CanonicalEvent


class EventConsumer:
    def __init__(
        self,
        topics: Sequence[str],
        *,
        group_id: str,
        bootstrap_servers: str | None = None,
    ) -> None:
        settings = get_settings()
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers or settings.redpanda_bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=orjson.loads,
        )

    async def __aenter__(self) -> "EventConsumer":
        await self._consumer.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._consumer.stop()

    async def events(self) -> AsyncIterator[CanonicalEvent]:
        async for message in self._consumer:
            yield CanonicalEvent.model_validate(message.value)

    async def commit(self) -> None:
        await self._consumer.commit()
