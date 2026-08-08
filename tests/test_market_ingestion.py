from datetime import UTC, datetime, timedelta

from scam2market.ingestion.archive import InMemoryRawEventArchive
from scam2market.ingestion.market import (
    MarketIngestionService,
    MarketProviderItem,
    ReplayProvider,
    SyntheticProvider,
)
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.repositories import InMemoryMarketRepository
from scam2market.schemas.domain import MarketTrade
from scam2market.state import InMemoryStateStore
from scam2market.streaming.publisher import InMemoryEventPublisher


def _trade(trade_id: str, event_time: datetime) -> MarketTrade:
    return MarketTrade(
        trade_id=trade_id,
        asset_id="S2MUSDT",
        event_time=event_time,
        price=1.25,
        quantity=100,
        side="BUY",
        source="test-market",
    )


def _service() -> tuple[
    MarketIngestionService,
    InMemoryMarketRepository,
    InMemoryStateStore,
    SourceQualityTracker,
]:
    repository = InMemoryMarketRepository()
    state = InMemoryStateStore()
    quality = SourceQualityTracker(freshness_threshold_seconds=30)
    service = MarketIngestionService(
        repository=repository,
        dedupe=state,
        state=state,
        archive=InMemoryRawEventArchive(),
        publisher=InMemoryEventPublisher(),
        quality=quality,
    )
    return service, repository, state, quality


async def test_duplicate_trade_does_not_double_count() -> None:
    event_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    provider = ReplayProvider([_trade("trade-1", event_time)], clock=lambda: event_time)
    event = [item async for item in provider.stream()][0]
    service, repository, _, _ = _service()

    assert await service.ingest(event) is True
    assert await service.ingest(event) is False
    assert len(repository.events) == 1


async def test_replay_is_deterministic_and_event_time_ordered_per_asset() -> None:
    provider = SyntheticProvider(clock=lambda: datetime(2026, 1, 2, tzinfo=UTC))

    first = [event async for event in provider.stream("replay-1")]
    second = [event async for event in provider.stream("replay-1")]

    assert len(first) == len(second) == 21
    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert [event.source_event_id for event in first] == [event.source_event_id for event in second]
    times = [event.event_time for event in first if event.asset_id == "S2MUSDT"]
    assert times == sorted(times)


async def test_source_gap_creates_degraded_quality_state() -> None:
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    provider = ReplayProvider(
        [
            MarketProviderItem(_trade("trade-1", start), source_sequence=1),
            MarketProviderItem(_trade("trade-3", start + timedelta(seconds=1)), source_sequence=3),
        ],
        source="gap-source",
        clock=lambda: start + timedelta(seconds=2),
    )
    service, _, _, quality = _service()

    assert await service.run_provider(provider) == 2
    state = quality.get("gap-source", "S2MUSDT")
    assert state is not None
    assert state.sequence_gap_count == 1
    assert state.status == "DEGRADED"


async def test_delayed_event_keeps_provider_event_time() -> None:
    event_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    ingested_at = event_time + timedelta(minutes=10)
    provider = ReplayProvider([_trade("late-trade", event_time)], clock=lambda: ingested_at)
    event = [item async for item in provider.stream()][0]
    service, repository, _, _ = _service()

    await service.ingest(event)

    stored = repository.events[event.dedupe_key()]
    assert stored.event_time == event_time
    assert event.ingested_at == ingested_at


async def test_latest_market_state_is_written_online() -> None:
    event_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    provider = ReplayProvider([_trade("trade-latest", event_time)], clock=lambda: event_time)
    event = [item async for item in provider.stream()][0]
    service, _, state, _ = _service()

    await service.ingest(event)

    latest = await state.get_json("latest:market:S2MUSDT")
    assert latest is not None
    assert latest["event_time"] == event_time
