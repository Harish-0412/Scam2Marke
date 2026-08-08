import asyncio
from datetime import UTC, datetime

from scam2market.schemas.events import CanonicalEvent, EventType
from scam2market.streaming.publisher import EventPublisher


async def main() -> None:
    now = datetime.now(tz=UTC)
    event = CanonicalEvent(
        event_type=EventType.market_trade_received,
        schema_version=1,
        source="synthetic",
        source_event_id="phase-1-smoke-trade-001",
        source_sequence=1,
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        partition_key="S2MUSDT",
        payload={"price": 1.23, "quantity": 1000, "side": "buy"},
    )
    publisher = EventPublisher()
    await publisher.start()
    try:
        await publisher.publish("market.trades.v1", event)
        print(f"published {event.event_type} with dedupe_key={event.dedupe_key()}")
    finally:
        await publisher.stop()


if __name__ == "__main__":
    asyncio.run(main())
