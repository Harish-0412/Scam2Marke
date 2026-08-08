from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from scam2market.features.schemas import FeatureSnapshot
from scam2market.intelligence.detectors import (
    CoordinationHeuristicDetector,
    DetectorOutput,
    LiquidityClassifier,
    MarketAnomalyDetector,
    MarketRegimeEngine,
    SocialSurgeDetector,
    TemporalLeadLagDetector,
)
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata
from scam2market.state import OnlineStateStore
from scam2market.streaming.publisher import CanonicalEventPublisher


class RiskLevel(StrEnum):
    normal = "NORMAL"
    watch = "WATCH"
    high = "HIGH"
    critical = "CRITICAL"


class ThresholdConfig(BaseModel):
    version: str = "fusion-thresholds-v1"
    watch: float = Field(default=0.35, ge=0, le=1)
    high: float = Field(default=0.60, ge=0, le=1)
    critical: float = Field(default=0.80, ge=0, le=1)


class FusionWeights(BaseModel):
    market_score: float = 0.35
    social_score: float = 0.20
    coordination_score: float = 0.15
    temporal_score: float = 0.15
    claim_risk: float = 0.15


class FusionResult(BaseModel):
    scope_id: str = "LIVE"
    asset_id: str
    feature_window_id: str
    feature_revision: int
    model_version: str
    market_score: float | None
    social_score: float | None
    coordination_score: float | None
    temporal_score: float | None
    claim_risk: float | None
    legitimate_event_score: float | None
    fusion_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    severity: RiskLevel
    missing_outputs: list[str]
    is_calibrated: bool
    market_regime: str
    liquidity_class: str
    scored_at: datetime


class ScoreRepository(Protocol):
    async def persist(self, result: FusionResult) -> bool: ...


class ScoreCalibrator(Protocol):
    def calibrate(self, score: float, *, market_regime: str, liquidity_class: str) -> float: ...


class FusionEngine:
    version = "fusion-v1"

    def __init__(
        self,
        *,
        weights: FusionWeights | None = None,
        thresholds: ThresholdConfig | None = None,
        calibrator: ScoreCalibrator | None = None,
    ) -> None:
        self._weights = weights or FusionWeights()
        self._thresholds = thresholds or ThresholdConfig()
        self._calibrator = calibrator

    def fuse(
        self,
        snapshot: FeatureSnapshot,
        outputs: list[DetectorOutput],
        *,
        claim_risk: float | None = None,
        legitimate_event_score: float | None = None,
        market_regime: str,
        liquidity_class: str,
    ) -> FusionResult:
        detector_values = {output.name: output.score for output in outputs}
        detector_values["claim_risk"] = claim_risk
        weighted_sum = 0.0
        available_weight = 0.0
        for name, weight in self._weights.model_dump().items():
            value = detector_values.get(name)
            if value is not None:
                weighted_sum += float(weight) * float(value)
                available_weight += float(weight)
        score = weighted_sum / available_weight if available_weight else 0.0
        if legitimate_event_score is not None:
            score *= 1.0 - 0.75 * max(0.0, min(1.0, legitimate_event_score))
        market_score = detector_values.get("market_score")
        corroborating_scores = [
            detector_values.get("social_score"),
            detector_values.get("coordination_score"),
            detector_values.get("temporal_score"),
            claim_risk,
        ]
        corroborated = any(value is not None and value >= 0.55 for value in corroborating_scores)
        if market_score is None or market_score < 0.35:
            score = min(score, self._thresholds.high - 0.01)

        missing = [
            name
            for name in (
                "market_score",
                "social_score",
                "coordination_score",
                "temporal_score",
                "claim_risk",
                "legitimate_event_score",
            )
            if (
                legitimate_event_score
                if name == "legitimate_event_score"
                else detector_values.get(name)
            )
            is None
        ]
        availability = 1.0 - len(missing) / 6.0
        baseline_confidence = float(snapshot.features["baseline_confidence"] or 0.0)
        data_quality = float(snapshot.features["data_quality_score"] or 0.0)
        confidence = max(
            0.0,
            min(1.0, availability * (0.4 + 0.35 * baseline_confidence + 0.25 * data_quality)),
        )
        score = max(0.0, min(1.0, score))
        is_calibrated = self._calibrator is not None and baseline_confidence >= 0.5
        if is_calibrated and self._calibrator is not None:
            score = max(
                0.0,
                min(
                    1.0,
                    self._calibrator.calibrate(
                        score,
                        market_regime=market_regime,
                        liquidity_class=liquidity_class,
                    ),
                ),
            )
        severity = self._severity(score)
        if severity == RiskLevel.critical and not (
            market_score is not None and market_score >= 0.65 and corroborated and confidence >= 0.4
        ):
            severity = RiskLevel.high
        if market_score is None and severity in {RiskLevel.high, RiskLevel.critical}:
            severity = RiskLevel.watch
        return FusionResult(
            scope_id=snapshot.scope_id,
            asset_id=snapshot.asset_id,
            feature_window_id=str(snapshot.feature_window_id),
            feature_revision=snapshot.revision,
            model_version=self.version,
            market_score=market_score,
            social_score=detector_values.get("social_score"),
            coordination_score=detector_values.get("coordination_score"),
            temporal_score=detector_values.get("temporal_score"),
            claim_risk=claim_risk,
            legitimate_event_score=legitimate_event_score,
            fusion_score=score,
            confidence=confidence,
            severity=severity,
            missing_outputs=missing,
            is_calibrated=is_calibrated,
            market_regime=market_regime,
            liquidity_class=liquidity_class,
            scored_at=datetime.now(tz=UTC),
        )

    def _severity(self, score: float) -> RiskLevel:
        if score >= self._thresholds.critical:
            return RiskLevel.critical
        if score >= self._thresholds.high:
            return RiskLevel.high
        if score >= self._thresholds.watch:
            return RiskLevel.watch
        return RiskLevel.normal


class DetectionService:
    def __init__(
        self,
        *,
        repository: ScoreRepository,
        state: OnlineStateStore,
        publisher: CanonicalEventPublisher,
        fusion: FusionEngine | None = None,
    ) -> None:
        self._repository = repository
        self._state = state
        self._publisher = publisher
        self._fusion = fusion or FusionEngine()
        self._market = MarketAnomalyDetector()
        self._social = SocialSurgeDetector()
        self._coordination = CoordinationHeuristicDetector()
        self._temporal = TemporalLeadLagDetector()
        self._regime = MarketRegimeEngine()
        self._liquidity = LiquidityClassifier()

    async def score(
        self,
        snapshot: FeatureSnapshot,
        *,
        claim_risk: float | None = None,
        legitimate_event_score: float | None = None,
    ) -> FusionResult:
        outputs = [
            self._market.score(snapshot),
            self._social.score(snapshot),
            self._coordination.score(snapshot),
            self._temporal.score(snapshot),
        ]
        regime, _ = self._regime.classify(snapshot)
        liquidity, _ = self._liquidity.classify(snapshot)
        result = self._fusion.fuse(
            snapshot,
            outputs,
            claim_risk=claim_risk,
            legitimate_event_score=legitimate_event_score,
            market_regime=regime.value,
            liquidity_class=liquidity.value,
        )
        persisted = await self._repository.persist(result)
        await self._state.set_json(
            f"latest:score:{snapshot.asset_id}", result.model_dump(mode="json")
        )
        await self._state.set_json(
            f"latest:score:{snapshot.scope_id}:{snapshot.asset_id}",
            result.model_dump(mode="json"),
        )
        if persisted:
            event = CanonicalEvent(
                event_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"fusion-event:{snapshot.scope_id}:{snapshot.feature_window_id}:"
                        f"{snapshot.revision}:{self._fusion.version}",
                    )
                ),
                event_type=EventType.model_fusion_scored,
                schema_version=1,
                source=self._fusion.version,
                source_event_id=(
                    f"{snapshot.scope_id}:{snapshot.feature_window_id}:"
                    f"{snapshot.revision}:{self._fusion.version}"
                ),
                asset_id=snapshot.asset_id,
                event_time=snapshot.window_end,
                ingested_at=result.scored_at,
                processed_at=result.scored_at,
                partition_key=snapshot.asset_id,
                replay=ReplayMetadata(
                    is_replay=snapshot.scope_id != "LIVE",
                    replay_session_id=(snapshot.scope_id if snapshot.scope_id != "LIVE" else None),
                ),
                payload=result.model_dump(mode="json"),
            )
            await self._publisher.publish("model.fusion.score.v1", event)
        return result


class InMemoryScoreRepository:
    def __init__(self) -> None:
        self.results: dict[tuple[str, int, str], FusionResult] = {}

    async def persist(self, result: FusionResult) -> bool:
        key = (result.feature_window_id, result.feature_revision, result.model_version)
        if key in self.results:
            return False
        self.results[key] = result
        return True
