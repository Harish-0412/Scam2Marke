import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from scam2market.common.time import utc_now
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.schemas.domain import MarketCandle, MarketTrade, OrderBookUpdate
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata
from scam2market.state import DedupeStore, OnlineStateStore
from scam2market.streaming.publisher import CanonicalEventPublisher

type MarketDatum = MarketTrade | MarketCandle | OrderBookUpdate


@dataclass(frozen=True, slots=True)
class MarketProviderItem:
    datum: MarketDatum
    source_sequence: int | None = None


class MarketProvider(Protocol):
    source: str

    def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]: ...


def _datum_id(datum: MarketDatum) -> str:
    if isinstance(datum, MarketTrade):
        return datum.trade_id
    if isinstance(datum, MarketCandle):
        return datum.candle_id
    return datum.update_id


def _event_type(datum: MarketDatum) -> EventType:
    if isinstance(datum, MarketTrade):
        return EventType.market_trade_received
    if isinstance(datum, MarketCandle):
        return EventType.market_candle_closed
    return EventType.market_orderbook_updated


def _topic(datum: MarketDatum) -> str:
    if isinstance(datum, MarketTrade):
        return "market.trades.v1"
    if isinstance(datum, MarketCandle):
        return "market.candles.v1"
    return "market.orderbook.v1"


class ReplayProvider:
    def __init__(
        self,
        records: Sequence[MarketProviderItem | MarketDatum],
        *,
        source: str = "market-replay",
        speed_multiplier: float = 0.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if speed_multiplier < 0:
            raise ValueError("speed_multiplier cannot be negative")
        self.source = source
        self._speed_multiplier = speed_multiplier
        self._clock = clock
        items = [
            record if isinstance(record, MarketProviderItem) else MarketProviderItem(record)
            for record in records
        ]
        self._items = sorted(
            items,
            key=lambda item: (
                item.datum.event_time,
                item.datum.asset_id,
                _datum_id(item.datum),
            ),
        )

    async def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]:
        previous_time: datetime | None = None
        session_id = replay_session_id or "standalone"
        for position, item in enumerate(self._items, start=1):
            datum = item.datum
            if self._speed_multiplier > 0 and previous_time is not None:
                delay = (datum.event_time - previous_time).total_seconds() / self._speed_multiplier
                if delay > 0:
                    await asyncio.sleep(delay)
            source_event_id = _datum_id(datum)
            origin_event_id = f"{self.source}:{source_event_id}"
            delivery_event_id = str(
                uuid5(NAMESPACE_URL, f"{self.source}:{session_id}:{source_event_id}")
            )
            yield CanonicalEvent(
                event_id=delivery_event_id,
                origin_event_id=origin_event_id,
                delivery_event_id=delivery_event_id,
                event_type=_event_type(datum),
                schema_version=1,
                source=self.source,
                source_event_id=source_event_id,
                source_sequence=item.source_sequence or position,
                asset_id=datum.asset_id,
                event_time=datum.event_time,
                ingested_at=datum.event_time if replay_session_id is not None else self._clock(),
                partition_key=datum.asset_id,
                replay=ReplayMetadata(
                    is_replay=replay_session_id is not None,
                    replay_session_id=replay_session_id,
                ),
                payload=datum.model_dump(mode="json"),
            )
            previous_time = datum.event_time


class SyntheticProvider(ReplayProvider):
    """Stable pump scenario used by tests, demos, and local development."""

    def __init__(
        self,
        *,
        asset_id: str = "S2MUSDT",
        source: str = "synthetic-market-v1",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        baseline_start = datetime(2026, 1, 1, 11, 55, tzinfo=UTC)
        start = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
        records: list[MarketDatum] = [
            MarketTrade(
                trade_id=f"synthetic-baseline-{index:03d}",
                asset_id=asset_id,
                event_time=baseline_start + timedelta(minutes=index),
                price=1.0,
                quantity=100.0,
                side="BUY" if index % 2 == 0 else "SELL",
                source=source,
            )
            for index in range(5)
        ]
        prices = [1.0, 1.01, 0.99, 1.02, 1.01, 1.05, 1.18, 1.42, 1.31, 1.08]
        quantities = [100, 95, 105, 98, 110, 180, 650, 1200, 900, 1400]
        for index, (price, quantity) in enumerate(zip(prices, quantities, strict=True)):
            event_time = start + timedelta(seconds=index * 15)
            records.append(
                MarketTrade(
                    trade_id=f"synthetic-trade-{index:03d}",
                    asset_id=asset_id,
                    event_time=event_time,
                    price=price,
                    quantity=float(quantity),
                    side="BUY" if index < 8 else "SELL",
                    source=source,
                )
            )
            records.append(
                OrderBookUpdate(
                    update_id=f"synthetic-book-{index:03d}",
                    asset_id=asset_id,
                    event_time=event_time + timedelta(milliseconds=1),
                    best_bid=price * 0.999,
                    best_ask=price * 1.001,
                    bids=[(price * 0.999, quantity * 0.8), (price * 0.998, quantity * 0.6)],
                    asks=[(price * 1.001, quantity * 0.5), (price * 1.002, quantity * 0.4)],
                    source=source,
                )
            )
        records.append(
            MarketTrade(
                trade_id="synthetic-watermark-tail",
                asset_id=asset_id,
                event_time=start + timedelta(minutes=8),
                price=1.02,
                quantity=10.0,
                side="BUY",
                source=source,
            )
        )
        super().__init__(records, source=source, clock=clock)


def normalize_market_event(event: CanonicalEvent) -> MarketDatum:
    payload = dict(event.payload)
    payload.update(
        asset_id=event.asset_id,
        event_time=event.event_time,
        source=event.source,
    )
    if event.event_type == EventType.market_trade_received:
        return MarketTrade.model_validate(payload)
    if event.event_type == EventType.market_candle_closed:
        return MarketCandle.model_validate(payload)
    if event.event_type == EventType.market_orderbook_updated:
        book = OrderBookUpdate.model_validate(payload)
        bid_depth = sum(quantity for _, quantity in book.bids[:5])
        ask_depth = sum(quantity for _, quantity in book.asks[:5])
        spread = (
            book.best_ask - book.best_bid
            if book.best_ask is not None and book.best_bid is not None
            else None
        )
        return book.model_copy(
            update={
                "spread": spread,
                "top_bid_depth": bid_depth or book.top_bid_depth,
                "top_ask_depth": ask_depth or book.top_ask_depth,
            }
        )
    raise ValueError(f"unsupported market event type: {event.event_type}")


class MarketIngestionService:
    def __init__(
        self,
        *,
        dedupe: DedupeStore,
        state: OnlineStateStore,
        publisher: CanonicalEventPublisher,
        quality: SourceQualityTracker,
    ) -> None:
        self._dedupe = dedupe
        self._state = state
        self._publisher = publisher
        self._quality = quality

    async def ingest(self, event: CanonicalEvent) -> bool:
        datum = normalize_market_event(event)
        dedupe_key = event.dedupe_key()
        if not await self._dedupe.claim(dedupe_key):
            return False
        topic = _topic(datum)
        try:
            quality = self._quality.observe(
                source=event.source,
                asset_id=datum.asset_id,
                event_time=event.event_time,
                ingested_at=event.ingested_at,
                sequence=event.source_sequence,
                is_orderbook=isinstance(datum, OrderBookUpdate),
            )
            quality_payload = quality.as_dict()
            published_event = event.model_copy(
                update={"payload": {**event.payload, "_quality": quality_payload}}
            )
            await self._publisher.publish(topic, published_event)
            latest = {
                "asset_id": datum.asset_id,
                "event_type": event.event_type.value,
                "event_time": event.event_time,
                "ingested_at": event.ingested_at,
                "source": event.source,
                "data": datum.model_dump(mode="json"),
                "quality": quality_payload,
            }
            await self._state.set_json(f"latest:market:{datum.asset_id}", latest)
            await self._state.set_json(
                f"source-health:market:{event.source}:{datum.asset_id}", quality_payload
            )
            return True
        except Exception:
            await self._dedupe.release(dedupe_key)
            raise

    async def run_provider(
        self, provider: MarketProvider, replay_session_id: str | None = None
    ) -> int:
        accepted = 0
        async for event in provider.stream(replay_session_id):
            accepted += int(await self.ingest(event))
        return accepted
