from datetime import UTC, datetime, timedelta
from uuid import UUID

from scam2market.evaluation.schemas import ScoreObservation
from scam2market.evaluation.service import (
    ABLATION_PROFILES,
    ReplayEvaluator,
    shadow_fusion_score,
)


def _observation(
    index: int, event_time: datetime, market: float, social: float, coordination: float
) -> ScoreObservation:
    return ScoreObservation(
        score_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
        event_time=event_time,
        scored_at=event_time,
        severity="NORMAL",
        confidence=0.8,
        components={
            "market_score": market,
            "social_score": social,
            "coordination_score": coordination,
            "temporal_score": coordination,
            "graph_score": coordination,
            "claim_risk": coordination,
            "legitimate_event_score": 0.0,
        },
        missing_output_count=0,
        data_freshness_seconds=2.0,
        processing_latency_ms=20 + index,
    )


def test_replay_evaluation_produces_metrics_and_cumulative_ablations() -> None:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    observations = [
        _observation(1, start, 0.1, 0.1, 0.1),
        _observation(2, start + timedelta(minutes=1), 0.2, 0.8, 0.8),
        _observation(3, start + timedelta(minutes=2), 0.9, 0.9, 0.9),
    ]
    evaluation = ReplayEvaluator().evaluate(
        replay_session_id=UUID("77777777-7777-7777-7777-777777777777"),
        manifest_hash="f" * 64,
        observations=observations,
        positive_from=start + timedelta(minutes=2),
        generated_at=start + timedelta(minutes=3),
    )

    assert evaluation.metrics.observation_count == 3
    assert evaluation.metrics.first_watch_at == start + timedelta(minutes=1)
    assert evaluation.metrics.lead_time_seconds == 60
    assert len(evaluation.ablations) == len(ABLATION_PROFILES) == 5
    assert [item.profile for item in evaluation.ablations] == [
        "MARKET_ONLY",
        "MARKET_SOCIAL",
        "COORDINATION",
        "GRAPH",
        "VERIFICATION",
    ]
    assert evaluation.metrics.p95_latency_ms == 23


def test_shadow_score_uses_versioned_weights() -> None:
    score = shadow_fusion_score(
        {"market_score": 0.8, "social_score": 0.2, "coordination_score": None},
        {"market_score": 0.75, "social_score": 0.25, "coordination_score": 0.0},
    )

    assert score == 0.65
