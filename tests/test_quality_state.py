from datetime import UTC, datetime, timedelta

from scam2market.ingestion.quality import OrderBookState, SourceQualityTracker


def test_orderbook_gap_requires_resync_before_features_are_valid() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    tracker = SourceQualityTracker(freshness_threshold_seconds=30)

    initial = tracker.observe(
        source="book",
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        sequence=1,
        is_orderbook=True,
    )
    initial_state = initial.orderbook_state
    gap = tracker.observe(
        source="book",
        asset_id="S2MUSDT",
        event_time=now + timedelta(seconds=1),
        ingested_at=now + timedelta(seconds=1),
        sequence=3,
        is_orderbook=True,
    )
    gap_state = gap.orderbook_state
    gap_valid = gap.book_valid
    resync = tracker.observe(
        source="book",
        asset_id="S2MUSDT",
        event_time=now + timedelta(seconds=2),
        ingested_at=now + timedelta(seconds=2),
        sequence=4,
        is_orderbook=True,
    )
    resync_state = resync.orderbook_state
    resync_valid = resync.book_valid
    recovered = tracker.observe(
        source="book",
        asset_id="S2MUSDT",
        event_time=now + timedelta(seconds=3),
        ingested_at=now + timedelta(seconds=3),
        sequence=5,
        is_orderbook=True,
    )

    assert initial_state == OrderBookState.valid
    assert gap_state == OrderBookState.gap_detected
    assert gap_valid is False
    assert resync_state == OrderBookState.resyncing
    assert resync_valid is False
    assert recovered.orderbook_state == OrderBookState.recovered
    assert recovered.book_valid is True


def test_stale_orderbook_is_not_valid_input() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    state = SourceQualityTracker(freshness_threshold_seconds=30).observe(
        source="book",
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now + timedelta(seconds=31),
        sequence=1,
        is_orderbook=True,
    )

    assert state.orderbook_state == OrderBookState.stale
    assert state.book_valid is False
    assert state.source_degraded is True
