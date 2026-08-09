import asyncio
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast

from scam2market.schemas.events import CanonicalEvent, EventType
from scam2market.streaming.publisher import EventPublisher


class _FakeTransactionalProducer:
    def __init__(self) -> None:
        self.in_transaction = False
        self.overlap_detected = False
        self.sent = 0

    def transaction(self) -> "_FakeTransactionalProducer":
        return self

    async def __aenter__(self) -> "_FakeTransactionalProducer":
        if self.in_transaction:
            self.overlap_detected = True
        self.in_transaction = True
        await asyncio.sleep(0)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.in_transaction = False

    async def send(self, *_: Any, **__: Any) -> None:
        await asyncio.sleep(0.01)
        self.sent += 1


def _event(event_id: str) -> CanonicalEvent:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return CanonicalEvent(
        event_id=event_id,
        event_type=EventType.market_trade_received,
        schema_version=1,
        source="test",
        source_event_id=event_id,
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        partition_key="S2MUSDT",
        payload={},
    )


async def test_concurrent_batches_are_serialized_on_shared_transactional_producer() -> None:
    publisher = EventPublisher("unused:9092")
    producer = _FakeTransactionalProducer()
    publisher._producer = cast(Any, producer)

    await asyncio.gather(
        publisher.publish("market.trades.v1", _event("event-1")),
        publisher.publish("market.trades.v1", _event("event-2")),
    )

    assert producer.sent == 2
    assert producer.overlap_detected is False
