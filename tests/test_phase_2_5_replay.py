from datetime import UTC, datetime

from scam2market.features.engine import FeatureWindowEngine
from scam2market.features.schemas import FeatureSnapshot
from scam2market.features.signals import market_signal, social_signals
from scam2market.ingestion.market import (
    MarketIngestionService,
    SyntheticProvider,
    normalize_market_event,
)
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.social import (
    AssetMentionResolver,
    AssetRegistry,
    AuthorPseudonymizer,
    SocialIngestionService,
    SyntheticSocialProvider,
)
from scam2market.intelligence.detectors import (
    CoordinationHeuristicDetector,
    LiquidityClassifier,
    MarketAnomalyDetector,
    MarketRegimeEngine,
    SocialSurgeDetector,
    TemporalLeadLagDetector,
)
from scam2market.intelligence.fusion import FusionEngine, RiskLevel
from scam2market.schemas.domain import Asset, AssetMention, AssetType, SocialPost
from scam2market.schemas.events import EventType
from scam2market.state import InMemoryStateStore
from scam2market.streaming.publisher import InMemoryEventPublisher


async def _scenario_snapshots(scope_id: str) -> dict[datetime, FeatureSnapshot]:
    state = InMemoryStateStore()
    market_publisher = InMemoryEventPublisher()
    social_publisher = InMemoryEventPublisher()
    asset = Asset(
        asset_id="S2MUSDT",
        symbol="S2M",
        name="Scam2Market Demo Asset",
        asset_type=AssetType.synthetic,
    )
    market = MarketIngestionService(
        dedupe=state,
        state=state,
        publisher=market_publisher,
        quality=SourceQualityTracker(30),
    )
    social = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=social_publisher,
        quality=SourceQualityTracker(300),
        pseudonymizer=AuthorPseudonymizer("integration-secret-at-least-16-characters"),
        resolver=AssetMentionResolver(AssetRegistry([asset])),
    )

    assert await market.run_provider(SyntheticProvider(), scope_id) == 26
    assert await social.run_provider(SyntheticSocialProvider(), scope_id) == 6

    signals = [
        market_signal(event, normalize_market_event(event)) for _, event in market_publisher.events
    ]
    posts = {
        str(event.payload["post_id"]): event
        for _, event in social_publisher.events
        if event.event_type == EventType.social_post_normalized
    }
    mention_events = {
        str(event.payload["post_id"]): event
        for _, event in social_publisher.events
        if event.event_type == EventType.social_asset_mention_detected
    }
    for post_id, post_event in posts.items():
        mention_event = mention_events[post_id]
        raw_mentions = mention_event.payload["mentions"]
        assert isinstance(raw_mentions, list)
        signals.extend(
            social_signals(
                mention_event,
                SocialPost.model_validate(post_event.payload),
                [AssetMention.model_validate(item) for item in raw_mentions],
            )
        )

    engine = FeatureWindowEngine(
        intervals_seconds=(60,),
        allowed_lateness_seconds=0,
        source_idle_after_seconds=300,
    )
    for signal in sorted(signals, key=lambda item: (item.event_time, item.event_id)):
        engine.ingest(signal)

    starts = (
        datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
        datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 12, 2, tzinfo=UTC),
    )
    snapshots = {start: engine.revisions("S2MUSDT", start, 60, scope_id)[-1] for start in starts}
    assert all(snapshot.is_final for snapshot in snapshots.values())
    return snapshots


def _risk(snapshot: FeatureSnapshot, claim_risk: float) -> tuple[float, RiskLevel, RiskLevel]:
    outputs = [
        MarketAnomalyDetector().score(snapshot),
        SocialSurgeDetector().score(snapshot),
        CoordinationHeuristicDetector().score(snapshot),
        TemporalLeadLagDetector().score(snapshot),
    ]
    regime, regime_confidence = MarketRegimeEngine().classify(snapshot)
    liquidity, liquidity_confidence = LiquidityClassifier().classify(snapshot)
    result = FusionEngine().fuse(
        snapshot,
        outputs,
        claim_risk=claim_risk,
        market_regime=regime.value,
        market_regime_confidence=regime_confidence,
        liquidity_class=liquidity.value,
        liquidity_confidence=liquidity_confidence,
    )
    return (
        result.context_adjusted_risk,
        result.social_coordination_severity,
        result.severity,
    )


async def test_deterministic_replay_preserves_early_warning_stage_transitions() -> None:
    first = await _scenario_snapshots("replay-a")
    second = await _scenario_snapshots("replay-b")
    baseline = datetime(2026, 1, 1, 11, 59, tzinfo=UTC)
    coordination = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    pump = datetime(2026, 1, 1, 12, 2, tzinfo=UTC)

    first_risks = {
        baseline: _risk(first[baseline], 0.0),
        coordination: _risk(first[coordination], 0.8),
        pump: _risk(first[pump], 0.8),
    }
    second_risks = {
        baseline: _risk(second[baseline], 0.0),
        coordination: _risk(second[coordination], 0.8),
        pump: _risk(second[pump], 0.8),
    }

    assert first_risks == second_risks
    assert first_risks[baseline][2] == RiskLevel.normal
    assert first_risks[coordination][1] in {RiskLevel.high, RiskLevel.critical}
    assert first_risks[coordination][2] in {RiskLevel.normal, RiskLevel.watch}
    assert first_risks[pump][2] in {RiskLevel.high, RiskLevel.critical}
