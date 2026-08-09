from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from scam2market.schemas.events import CanonicalEvent
from scam2market.streaming.publisher import CanonicalEventPublisher


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    outbox_id: UUID
    topic: str
    event: CanonicalEvent


class OutboxRepository(Protocol):
    async def pending(self, limit: int = 100) -> list[OutboxMessage]: ...

    async def mark_published(self, outbox_id: UUID) -> None: ...

    async def mark_failed(self, outbox_id: UUID, error: str | None = None) -> None: ...


class OutboxDispatcher:
    def __init__(
        self,
        *,
        repository: OutboxRepository,
        publisher: CanonicalEventPublisher,
    ) -> None:
        self._repository = repository
        self._publisher = publisher

    async def dispatch_batch(self, limit: int = 100) -> int:
        published = 0
        for message in await self._repository.pending(limit):
            try:
                await self._publisher.publish(message.topic, message.event)
            except Exception as error:
                await self._repository.mark_failed(message.outbox_id, repr(error))
                continue
            await self._repository.mark_published(message.outbox_id)
            published += 1
        return published
