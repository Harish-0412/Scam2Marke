import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from scam2market.campaigns.repository import InMemoryCampaignRepository
from scam2market.campaigns.schemas import AlertType, CampaignStage
from scam2market.campaigns.service import CampaignService
from scam2market.intelligence.fusion import FusionResult, RiskLevel
from scam2market.schemas.events import CanonicalEvent, EventType

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _score(
    *,
    severity: RiskLevel = RiskLevel.watch,
    market: float = 0.2,
    social: float = 0.7,
    coordination: float = 0.3,
    price_return: float = 0.01,
    pressure: float = 0.1,
) -> FusionResult:
    return FusionResult(
        asset_id="S2MUSDT",
        feature_window_id=str(uuid4()),
        feature_revision=1,
        model_version="fusion-v2",
        market_score=market,
        social_score=social,
        coordination_score=coordination,
        temporal_score=0.4,
        claim_risk=None,
        legitimate_event_score=None,
        graph_score=None,
        market_anomaly_risk=market,
        market_anomaly_severity=severity,
        social_coordination_risk=social,
        social_coordination_severity=severity,
        raw_cross_domain_risk=max(market, social),
        context_adjusted_risk=max(market, social),
        fusion_score=max(market, social),
        confidence=0.8,
        severity=severity,
        missing_outputs=[],
        is_calibrated=False,
        market_regime="DISLOCATED",
        market_regime_confidence=0.8,
        liquidity_class="LOW",
        liquidity_confidence=0.8,
        stage_signals={
            "price_return": price_return,
            "relative_volume": 5.0,
            "spread": 0.01,
            "orderbook_imbalance": 0.2,
            "buy_sell_pressure": pressure,
            "mention_count": 20.0,
        },
        scored_at=START,
    )


def _event(sequence: int, score: FusionResult) -> CanonicalEvent:
    at = START + timedelta(minutes=sequence)
    return CanonicalEvent(
        event_id=str(uuid4()),
        event_type=EventType.model_fusion_scored,
        schema_version=1,
        source=score.model_version,
        source_event_id=f"score-{sequence}",
        asset_id=score.asset_id,
        event_time=at,
        ingested_at=at,
        partition_key=score.asset_id,
        payload=score.model_dump(mode="json"),
    )


async def test_same_evidence_is_idempotent_and_suppresses_repeat_notifications() -> None:
    repository = InMemoryCampaignRepository(suppression_seconds=300)
    service = CampaignService(repository)
    event = _event(1, _score())

    first = await service.process(event)
    duplicate = await service.process(event)
    repeated = await service.process(_event(2, _score()))

    assert duplicate.duplicate_evidence is True
    alert = repository.alerts[(first.campaign.campaign_id, AlertType.social_hype_surge)]
    assert alert.occurrence_count == 2
    assert repeated.alerts
    assert repository.alert_history[-1][2] is True


async def test_campaign_stage_machine_records_valid_progression_and_severity_change() -> None:
    repository = InMemoryCampaignRepository()
    service = CampaignService(repository)

    early = await service.process(_event(1, _score()))
    coordinated = await service.process(
        _event(2, _score(coordination=0.8, severity=RiskLevel.high))
    )
    pump = await service.process(
        _event(
            3,
            _score(
                market=0.9,
                social=0.8,
                coordination=0.8,
                severity=RiskLevel.high,
                price_return=0.3,
            ),
        )
    )
    dump = await service.process(
        _event(
            4,
            _score(
                market=0.9,
                social=0.6,
                coordination=0.8,
                severity=RiskLevel.critical,
                price_return=-0.12,
                pressure=-0.7,
            ),
        )
    )

    assert early.campaign.stage == CampaignStage.early_social_seeding
    assert coordinated.campaign.stage == CampaignStage.coordinated_amplification
    assert pump.campaign.stage == CampaignStage.market_pump
    assert dump.campaign.stage == CampaignStage.dump
    assert len(repository.stage_history) == 3
    assert any(severity == RiskLevel.critical for _, severity, _ in repository.alert_history)


async def test_concurrent_campaign_updates_do_not_create_two_campaigns() -> None:
    repository = InMemoryCampaignRepository()
    service = CampaignService(repository)
    first = await service.process(_event(1, _score()))

    await asyncio.gather(
        service.process(_event(2, _score(coordination=0.8, severity=RiskLevel.high))),
        service.process(_event(3, _score(coordination=0.9, severity=RiskLevel.high))),
    )

    assert len(repository.campaigns) == 1
    assert len(repository.evidence_ids) == 3
    assert repository.campaigns[("LIVE", "S2MUSDT")].campaign_id == first.campaign.campaign_id
