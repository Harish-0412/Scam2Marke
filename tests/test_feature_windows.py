from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scam2market.features.engine import (
    FeatureWindowEngine,
    FeatureWindowService,
    InMemoryFeatureRepository,
)
from scam2market.features.schemas import (
    FEATURE_NAMES,
    FeatureSignal,
    FeatureSnapshot,
    ModelInput,
    RevisionState,
    SignalKind,
    SourceDomain,
)
from scam2market.intelligence.detectors import MarketAnomalyDetector
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
        source_domain=SourceDomain.market,
        values={"price": price, "quantity": 100, "side": "BUY"},
    )


def test_late_event_creates_new_revision_of_finalized_window() -> None:
    engine = FeatureWindowEngine(
        intervals_seconds=(60,),
        allowed_lateness_seconds=0,
        required_domains=(SourceDomain.market,),
    )
    engine.ingest(_trade_signal("trade-1", START, 1.0))
    engine.ingest(_trade_signal("future", START + timedelta(minutes=2), 1.2))

    before = engine.revisions("S2MUSDT", START, 60)
    assert before[-1].is_final is True
    assert before[-1].features["trade_count"] == 1

    engine.ingest(_trade_signal("late", START + timedelta(seconds=30), 1.1))
    after = engine.revisions("S2MUSDT", START, 60)

    assert after[-1].revision == before[-1].revision + 1
    assert after[-1].is_final is True
    assert after[-1].revision_state == RevisionState.corrected
    assert after[-1].supersedes_revision == before[-1].revision
    assert after[-1].features["trade_count"] == 2
    assert before[-1].features["trade_count"] == 1


def test_replay_regenerates_identical_final_features_and_lineage() -> None:
    signals = [
        _trade_signal("trade-1", START, 1.0),
        _trade_signal("trade-2", START + timedelta(seconds=30), 1.2),
        _trade_signal("future", START + timedelta(minutes=2), 1.1),
    ]
    engines = [
        FeatureWindowEngine(
            intervals_seconds=(60,),
            allowed_lateness_seconds=0,
            required_domains=(SourceDomain.market,),
        ),
        FeatureWindowEngine(
            intervals_seconds=(60,),
            allowed_lateness_seconds=0,
            required_domains=(SourceDomain.market,),
        ),
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
    engine = FeatureWindowEngine(
        intervals_seconds=(60,),
        allowed_lateness_seconds=0,
        required_domains=(SourceDomain.market,),
    )
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
            feature_schema_hash=model_input.feature_schema_hash,
            feature_names=list(reversed(model_input.feature_names)),
            values=model_input.values,
        )


def test_feature_snapshot_canonicalizes_json_object_key_order() -> None:
    snapshot = FeatureWindowEngine(intervals_seconds=(60,)).ingest(
        _trade_signal("canonical-order", START)
    )[0]
    serialized = snapshot.model_dump(mode="json")
    serialized["features"] = dict(reversed(list(serialized["features"].items())))

    restored = FeatureSnapshot.model_validate(serialized)

    assert tuple(restored.features) == FEATURE_NAMES


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


def test_combined_watermark_waits_for_both_source_domains() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,), allowed_lateness_seconds=0)
    engine.ingest(_trade_signal("market-start", START))
    engine.ingest(_trade_signal("market-future", START + timedelta(minutes=2)))

    assert engine.revisions("S2MUSDT", START, 60)[-1].revision_state == RevisionState.provisional
    assert engine.watermarks("LIVE", "S2MUSDT")["fusion"] is None

    social_start = FeatureSignal(
        event_id="social-start",
        asset_id="S2MUSDT",
        event_time=START,
        ingested_at=START,
        kind=SignalKind.social_post,
        source_domain=SourceDomain.social,
        values={"author_id": "actor-1"},
    )
    engine.ingest(social_start)
    engine.ingest(
        social_start.model_copy(
            update={
                "event_id": "social-future",
                "event_time": START + timedelta(minutes=2),
                "ingested_at": START + timedelta(minutes=2),
            }
        )
    )

    final = engine.revisions("S2MUSDT", START, 60)[-1]
    assert final.revision_state == RevisionState.final
    assert engine.watermarks("LIVE", "S2MUSDT")["fusion"] == START + timedelta(minutes=2)


def test_quiet_observed_source_becomes_idle_but_unavailable_source_does_not() -> None:
    engine = FeatureWindowEngine(
        intervals_seconds=(60,),
        allowed_lateness_seconds=0,
        source_idle_after_seconds=60,
    )
    engine.ingest(_trade_signal("market-start", START))
    social = FeatureSignal(
        event_id="social-start",
        asset_id="S2MUSDT",
        event_time=START,
        ingested_at=START,
        kind=SignalKind.social_post,
        source_domain=SourceDomain.social,
        values={"author_id": "actor-1"},
    )
    engine.ingest(social)
    engine.ingest(_trade_signal("market-future", START + timedelta(minutes=2)))

    final = engine.revisions("S2MUSDT", START, 60)[-1]
    assert final.revision_state == RevisionState.final
    assert final.features["social_source_idle"] == 1

    unavailable = FeatureWindowEngine(
        intervals_seconds=(60,),
        allowed_lateness_seconds=0,
        source_idle_after_seconds=60,
    )
    unavailable.ingest(_trade_signal("only-market", START))
    unavailable.ingest(_trade_signal("only-market-future", START + timedelta(minutes=2)))
    assert unavailable.watermarks("LIVE", "S2MUSDT")["social"] is None
    assert unavailable.revisions("S2MUSDT", START, 60)[-1].is_final is False


def test_invalid_orderbook_is_null_without_disabling_remaining_market_detector() -> None:
    engine = FeatureWindowEngine(intervals_seconds=(60,), required_domains=(SourceDomain.market,))
    engine.ingest(_trade_signal("trade", START, 1.2))
    engine.ingest(
        FeatureSignal(
            event_id="invalid-book",
            asset_id="S2MUSDT",
            event_time=START + timedelta(seconds=1),
            ingested_at=START + timedelta(seconds=1),
            kind=SignalKind.orderbook,
            source_domain=SourceDomain.market,
            values={
                "spread": None,
                "top_n_depth": None,
                "imbalance": None,
                "book_valid": False,
            },
        )
    )
    snapshot = engine.ingest(
        FeatureSignal(
            event_id="market-quality",
            asset_id="S2MUSDT",
            event_time=START + timedelta(seconds=2),
            ingested_at=START + timedelta(seconds=2),
            kind=SignalKind.data_quality,
            source_domain=SourceDomain.market,
            values={
                "source_active": True,
                "source_degraded": True,
                "source_gap_count": 4,
            },
        )
    )[-1]
    output = MarketAnomalyDetector().score(snapshot)

    assert snapshot.features["spread"] is None
    assert snapshot.features["top_n_depth"] is None
    assert snapshot.features["orderbook_imbalance"] is None
    assert snapshot.features["orderbook_valid"] == 0
    assert float(snapshot.features["data_quality_score"] or 0.0) < 1.0
    assert output.score is not None
    assert "orderbook excluded" in output.reason
