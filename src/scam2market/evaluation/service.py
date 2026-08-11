from datetime import datetime
from statistics import fmean
from uuid import NAMESPACE_URL, UUID, uuid5

from scam2market.evaluation.schemas import (
    AblationResult,
    EvaluationMetrics,
    ReplayEvaluation,
    ScoreObservation,
)

EVALUATION_VERSION = "replay-evaluation-v1"

ABLATION_PROFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MARKET_ONLY", ("market_score",)),
    ("MARKET_SOCIAL", ("market_score", "social_score")),
    (
        "COORDINATION",
        ("market_score", "social_score", "coordination_score", "temporal_score"),
    ),
    (
        "GRAPH",
        ("market_score", "social_score", "coordination_score", "temporal_score", "graph_score"),
    ),
    (
        "VERIFICATION",
        (
            "market_score",
            "social_score",
            "coordination_score",
            "temporal_score",
            "graph_score",
            "claim_risk",
            "legitimate_event_score",
        ),
    ),
)

WEIGHTS = {
    "market_score": 0.40,
    "social_score": 0.10,
    "coordination_score": 0.18,
    "temporal_score": 0.10,
    "graph_score": 0.10,
    "claim_risk": 0.12,
}


class ReplayEvaluator:
    def evaluate(
        self,
        *,
        replay_session_id: UUID,
        manifest_hash: str,
        observations: list[ScoreObservation],
        positive_from: datetime,
        generated_at: datetime,
    ) -> ReplayEvaluation:
        ordered = sorted(observations, key=lambda item: (item.event_time, str(item.score_id)))
        baseline_scores = [self._profile_score(item.components, None) for item in ordered]
        metrics = self._metrics(ordered, baseline_scores, positive_from)
        ablations: list[AblationResult] = []
        previous_peak = 0.0
        for profile, components in ABLATION_PROFILES:
            scores = [self._profile_score(item.components, components) for item in ordered]
            profile_metrics = self._metrics(ordered, scores, positive_from)
            ablations.append(
                AblationResult(
                    profile=profile,
                    components=list(components),
                    metrics=profile_metrics,
                    contribution_delta=round(profile_metrics.peak_score - previous_peak, 6),
                )
            )
            previous_peak = profile_metrics.peak_score
        evaluation_id = uuid5(
            NAMESPACE_URL,
            f"evaluation:{replay_session_id}:{EVALUATION_VERSION}:{manifest_hash}",
        )
        return ReplayEvaluation(
            evaluation_id=evaluation_id,
            replay_session_id=replay_session_id,
            evaluation_version=EVALUATION_VERSION,
            manifest_hash=manifest_hash,
            metrics=metrics,
            ablations=ablations,
            generated_at=generated_at,
        )

    @staticmethod
    def _profile_score(
        components: dict[str, float | None], allowed: tuple[str, ...] | None
    ) -> float:
        selected = set(allowed or (*WEIGHTS, "legitimate_event_score"))
        weighted_sum = 0.0
        available_weight = 0.0
        for name, weight in WEIGHTS.items():
            value = components.get(name)
            if name in selected and value is not None:
                weighted_sum += value * weight
                available_weight += weight
        score = weighted_sum / available_weight if available_weight else 0.0
        if "legitimate_event_score" in selected:
            score *= 1 - 0.35 * (components.get("legitimate_event_score") or 0.0)
        if (components.get("market_score") or 0.0) < 0.35:
            score = min(score, 0.59)
        return round(max(0.0, min(1.0, score)), 6)

    @staticmethod
    def _metrics(
        observations: list[ScoreObservation], scores: list[float], positive_from: datetime
    ) -> EvaluationMetrics:
        severities = [_severity(score) for score in scores]
        first_watch = _first_time(observations, severities, {"WATCH", "HIGH", "CRITICAL"})
        first_high = _first_time(observations, severities, {"HIGH", "CRITICAL"})
        first_critical = _first_time(observations, severities, {"CRITICAL"})
        predicted_positive = [severity in {"HIGH", "CRITICAL"} for severity in severities]
        true_predictions = sum(
            predicted and item.event_time >= positive_from
            for item, predicted in zip(observations, predicted_positive, strict=True)
        )
        positive_predictions = sum(predicted_positive)
        negative_indices = [
            index for index, item in enumerate(observations) if item.event_time < positive_from
        ]
        false_positives = sum(predicted_positive[index] for index in negative_indices)
        latencies = sorted(item.processing_latency_ms for item in observations)
        freshness = [
            item.data_freshness_seconds
            for item in observations
            if item.data_freshness_seconds is not None
        ]
        return EvaluationMetrics(
            observation_count=len(observations),
            alert_count=positive_predictions,
            watch_or_higher_count=sum(level != "NORMAL" for level in severities),
            first_watch_at=first_watch,
            first_high_at=first_high,
            first_critical_at=first_critical,
            lead_time_seconds=(
                (positive_from - first_watch).total_seconds() if first_watch is not None else None
            ),
            hard_negative_precision_proxy=round(
                true_predictions / positive_predictions if positive_predictions else 1.0, 6
            ),
            false_positive_rate=round(
                false_positives / len(negative_indices) if negative_indices else 0.0, 6
            ),
            mean_confidence=round(
                fmean(item.confidence for item in observations) if observations else 0.0, 6
            ),
            missing_output_rate=round(
                fmean(item.missing_output_count / 7 for item in observations)
                if observations
                else 0.0,
                6,
            ),
            p50_latency_ms=_percentile(latencies, 0.50),
            p95_latency_ms=_percentile(latencies, 0.95),
            mean_data_freshness_seconds=round(fmean(freshness), 6) if freshness else None,
            peak_score=max(scores, default=0.0),
        )


def shadow_fusion_score(components: dict[str, float | None], weights: dict[str, float]) -> float:
    weighted_sum = sum(
        value * weights.get(name, 0.0) for name, value in components.items() if value is not None
    )
    available = sum(
        weights.get(name, 0.0) for name, value in components.items() if value is not None
    )
    return round(max(0.0, min(1.0, weighted_sum / available if available else 0.0)), 6)


def _severity(score: float) -> str:
    if score >= 0.8:
        return "CRITICAL"
    if score >= 0.6:
        return "HIGH"
    if score >= 0.35:
        return "WATCH"
    return "NORMAL"


def _first_time(
    observations: list[ScoreObservation], severities: list[str], accepted: set[str]
) -> datetime | None:
    return next(
        (
            item.event_time
            for item, severity in zip(observations, severities, strict=True)
            if severity in accepted
        ),
        None,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, round((len(values) - 1) * fraction))
    return round(values[index], 3)
