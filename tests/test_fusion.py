from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from scam2market.features.schemas import (
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    FeatureLineage,
    FeatureSnapshot,
    RevisionState,
)
from scam2market.intelligence.detectors import (
    CoordinationHeuristicDetector,
    MarketAnomalyDetector,
    SocialSurgeDetector,
)
from scam2market.intelligence.fusion import (
    DetectionService,
    FusionEngine,
    InMemoryScoreRepository,
    RiskLevel,
)
from scam2market.state import InMemoryStateStore
from scam2market.streaming.publisher import InMemoryEventPublisher

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot(**overrides: float | int | None) -> FeatureSnapshot:
    defaults: dict[str, float | int | None] = {name: 0.0 for name in FEATURE_NAMES}
    defaults.update(
        {
            "spread": None,
            "top_n_depth": None,
            "orderbook_imbalance": None,
            "social_lead_seconds": None,
            "data_quality_score": 1.0,
            "baseline_confidence": 0.8,
        }
    )
    defaults.update(overrides)
    window_id = uuid5(NAMESPACE_URL, "fusion-test-window")
    return FeatureSnapshot(
        feature_window_id=window_id,
        asset_id="S2MUSDT",
        window_start=START,
        window_end=START + timedelta(minutes=1),
        interval_seconds=60,
        revision=1,
        is_final=True,
        revision_state=RevisionState.final,
        feature_schema_version=FEATURE_SCHEMA.feature_schema,
        features=defaults,
        lineage=FeatureLineage(
            lineage_id=uuid5(NAMESPACE_URL, "fusion-test-lineage"),
            source_event_ids=["event-1"],
            source_event_min_time=START,
            source_event_max_time=START,
            source_count=1,
            source_hash="a" * 64,
        ),
    )


def test_market_detector_flags_abnormal_price_and_volume() -> None:
    output = MarketAnomalyDetector().score(
        _snapshot(price_return=0.35, relative_volume=8.0, volatility=0.12, trade_count=40)
    )

    assert output.score is not None
    assert output.score >= 0.8


def test_social_detector_flags_mention_velocity() -> None:
    output = SocialSurgeDetector().score(
        _snapshot(
            mention_count=20,
            unique_author_count=12,
            hashtag_velocity=15,
            new_author_ratio=0.9,
        )
    )

    assert output.score is not None
    assert output.score >= 0.9


async def test_social_hype_alone_cannot_create_critical_alert() -> None:
    service = DetectionService(
        repository=InMemoryScoreRepository(),
        state=InMemoryStateStore(),
        publisher=InMemoryEventPublisher(),
    )
    social_only = _snapshot(
        mention_count=50,
        unique_author_count=30,
        hashtag_velocity=30,
        new_author_ratio=1.0,
        author_concentration=1.0,
        repost_reply_ratio=1.0,
        url_concentration=1.0,
    )

    result = await service.score(social_only, claim_risk=1.0)

    assert result.market_score is None
    assert result.severity in {RiskLevel.normal, RiskLevel.watch}
    assert result.social_coordination_severity == RiskLevel.critical
    assert "market_score" in {item.name for item in result.missing_outputs}


async def test_degraded_data_quality_reduces_confidence() -> None:
    service = DetectionService(
        repository=InMemoryScoreRepository(),
        state=InMemoryStateStore(),
        publisher=InMemoryEventPublisher(),
    )
    healthy = _snapshot(
        trade_count=20,
        volume=100_000,
        relative_volume=4,
        data_quality_score=1.0,
    )
    degraded = healthy.model_copy(
        update={
            "feature_window_id": uuid5(NAMESPACE_URL, "degraded-window"),
            "features": {**healthy.features, "data_quality_score": 0.1},
        }
    )

    healthy_result = await service.score(healthy)
    degraded_result = await service.score(degraded)

    assert degraded_result.confidence < healthy_result.confidence


def test_legitimate_event_evidence_reduces_fusion_score() -> None:
    snapshot = _snapshot(
        price_return=0.3,
        relative_volume=7,
        volatility=0.1,
        trade_count=40,
        mention_count=20,
        unique_author_count=10,
        hashtag_velocity=15,
        social_lead_seconds=180,
    )
    outputs = [
        MarketAnomalyDetector().score(snapshot),
        SocialSurgeDetector().score(snapshot),
    ]
    fusion = FusionEngine()

    unexplained = fusion.fuse(
        snapshot,
        outputs,
        claim_risk=0.8,
        market_regime="DISLOCATED",
        market_regime_confidence=0.9,
        liquidity_class="LOW",
        liquidity_confidence=0.8,
    )
    explained = fusion.fuse(
        snapshot,
        outputs,
        claim_risk=0.8,
        legitimate_event_score=1.0,
        market_regime="DISLOCATED",
        market_regime_confidence=0.9,
        liquidity_class="LOW",
        liquidity_confidence=0.8,
    )

    assert explained.fusion_score < unexplained.fusion_score


def test_legitimate_event_adjustment_cannot_erase_corroborated_risk() -> None:
    snapshot = _snapshot(
        price_return=0.4,
        relative_volume=9,
        volatility=0.15,
        trade_count=50,
        mention_count=30,
        unique_author_count=3,
        author_concentration=1.0,
        repost_reply_ratio=1.0,
        url_concentration=1.0,
    )
    outputs = [
        MarketAnomalyDetector().score(snapshot),
        CoordinationHeuristicDetector().score(snapshot),
    ]

    result = FusionEngine().fuse(
        snapshot,
        outputs,
        legitimate_event_score=1.0,
        market_regime="DISLOCATED",
        market_regime_confidence=0.9,
        liquidity_class="LOW",
        liquidity_confidence=0.8,
    )

    assert result.context_adjusted_risk >= 0.35
    assert result.raw_cross_domain_risk >= result.context_adjusted_risk
