from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scam2market.features.engine import (
    FeatureWindowEngine,
    FeatureWindowService,
    InMemoryFeatureRepository,
)
from scam2market.features.schemas import FeatureSignal, ModelInput, SignalKind
from scam2market.state import InMemoryStateStore
from scam2market.streaming.publisher import InMemoryEventPublisher

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _trade_signal(event_id: str, event_time: datetime, price: float = 1.0) -> FeatureSignal:
    return FeatureSignal(
        event_id=event_id,
        asset_id="S2MUSDT",
        event_time=event_time,
        ingested_at=event_time + timedelta(seconds=1),
        kind=SignalKind.market_trade,
        values={"price": price, "quantity": 100, "side": "BUY"},
    )


def test_late_event_creates_new_revision_of_finalized_window() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,), allowed_lateness_seconds=0)
    engine.ingest(_trade_signal("trade-1", START, 1.0))
    engine.ingest(_trade_signal("future", START + timedelta(minutes=2), 1.2))

    before = engine.revisions("S2MUSDT", START, 60)
    assert before[-1].is_final is True
    assert before[-1].features["trade_count"] == 1

    engine.ingest(_trade_signal("late", START + timedelta(seconds=30), 1.1))
    after = engine.revisions("S2MUSDT", START, 60)

    assert after[-1].revision == before[-1].revision + 1
    assert after[-1].is_final is True
    assert after[-1].features["trade_count"] == 2
    assert before[-1].features["trade_count"] == 1


def test_replay_regenerates_identical_final_features_and_lineage() -> None:
    signals = [
        _trade_signal("trade-1", START, 1.0),
        _trade_signal("trade-2", START + timedelta(seconds=30), 1.2),
        _trade_signal("future", START + timedelta(minutes=2), 1.1),
    ]
    engines = [
        FeatureWindowEngine(intervals_seconds=(60,), allowed_lateness_seconds=0),
        FeatureWindowEngine(intervals_seconds=(60,), allowed_lateness_seconds=0),
    ]
    for engine in engines:
        for signal in signals:
            engine.ingest(signal)

    first = engines[0].revisions("S2MUSDT", START, 60)[-1]
    second = engines[1].revisions("S2MUSDT", START, 60)[-1]

    assert first.features == second.features
    assert first.lineage.source_hash == second.lineage.source_hash
    assert first.lineage.source_event_ids == ["trade-1", "trade-2"]
    assert first.lineage.source_count == 2


def test_relative_volume_uses_trailing_baseline_and_late_event_cascades() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,), allowed_lateness_seconds=0)
    engine.ingest(_trade_signal("baseline", START, 1.0))
    pump = _trade_signal("pump", START + timedelta(minutes=1), 1.0).model_copy(
        update={"values": {"price": 1.0, "quantity": 500, "side": "BUY"}}
    )
    engine.ingest(pump)
    engine.ingest(_trade_signal("watermark", START + timedelta(minutes=3), 1.0))
    pump_start = START + timedelta(minutes=1)
    before = engine.revisions("S2MUSDT", pump_start, 60)[-1]

    assert before.features["relative_volume"] == 5.0

    late = _trade_signal("late-baseline", START + timedelta(seconds=30), 1.0)
    engine.ingest(late)
    after = engine.revisions("S2MUSDT", pump_start, 60)[-1]

    assert after.revision > before.revision
    assert after.features["relative_volume"] == 2.5


def test_replay_scopes_isolate_identical_source_events() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,))
    signal = _trade_signal("same-event", START)

    first = engine.ingest(signal.model_copy(update={"scope_id": "replay-1"}))[0]
    second = engine.ingest(signal.model_copy(update={"scope_id": "replay-2"}))[0]

    assert first.feature_window_id != second.feature_window_id
    assert first.scope_id == "replay-1"
    assert second.scope_id == "replay-2"
    assert len(engine.revisions("S2MUSDT", START, 60, "replay-1")) == 1
    assert len(engine.revisions("S2MUSDT", START, 60, "replay-2")) == 1


def test_model_input_rejects_reordered_features() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,))
    snapshot = engine.ingest(_trade_signal("trade-1", START))[0]
    model_input = ModelInput.from_snapshot(snapshot)

    with pytest.raises(ValidationError):
        ModelInput(
            feature_schema_version=model_input.feature_schema_version,
            feature_names=list(reversed(model_input.feature_names)),
            values=model_input.values,
        )


async def test_latest_redis_state_matches_latest_persisted_snapshot() -> None:
    repository = InMemoryFeatureRepository()
    state = InMemoryStateStore()
    service = FeatureWindowService(
        engine=FeatureWindowEngine(intervals_seconds=(60,)),
        repository=repository,
        state=state,
        publisher=InMemoryEventPublisher(),
    )

    snapshots = await service.process(_trade_signal("trade-1", START))
    latest = await state.get_json("latest:features:S2MUSDT:60")

    assert latest is not None
    assert latest["revision"] == snapshots[-1].revision
    assert repository.history[-1].model_dump(mode="json") == latest
