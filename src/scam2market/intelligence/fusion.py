import hashlib
import json
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
    MissingReason,
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


class EnrichmentProfile(StrEnum):
    base = "BASE"
    graph = "GRAPH"
    verification = "VERIFICATION"
    graph_and_verification = "GRAPH_AND_VERIFICATION"


class ThresholdConfig(BaseModel):
    version: str = "fusion-thresholds-v1"
    watch: float = Field(default=0.35, ge=0, le=1)
    high: float = Field(default=0.60, ge=0, le=1)
    critical: float = Field(default=0.80, ge=0, le=1)


class FusionWeights(BaseModel):
    market_score: float = 0.40
    social_score: float = 0.10
    coordination_score: float = 0.18
    temporal_score: float = 0.10
    claim_risk: float = 0.12
    graph_score: float = 0.10


class MissingOutput(BaseModel):
    name: str
    reason: MissingReason


class ContributionDirection(StrEnum):
    risk_increasing = "RISK_INCREASING"
    risk_reducing = "RISK_REDUCING"
    neutral = "NEUTRAL"


class TraceComponent(BaseModel):
    name: str
    value: float | None
    configured_weight: float
    effective_normalized_weight: float
    signed_weighted_contribution: float
    direction: ContributionDirection
    missing: bool
    missing_reason: MissingReason | None = None


class ScoreAdjustment(BaseModel):
    name: str
    before: float
    factor: float | None = None
    delta: float
    after: float
    direction: ContributionDirection


class PolicyDecision(BaseModel):
    policy: str
    applied: bool
    before: float
    after: float
    reason: str


class DecisionTrace(BaseModel):
    version: str = "fusion-decision-trace-v1"
    components: list[TraceComponent]
    adjustments: list[ScoreAdjustment]
    policy_decisions: list[PolicyDecision]
    thresholds: ThresholdConfig
    raw_weighted_score: float
    final_score: float


class ThreatContextStatus(StrEnum):
    disabled = "DISABLED"
    unavailable = "UNAVAILABLE"
    stale = "STALE"
    no_match = "NO_MATCH"
    matched = "MATCHED"


class ThreatContext(BaseModel):
    status: ThreatContextStatus = ThreatContextStatus.disabled
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    snapshot_id: str | None = None
    match_ids: list[str] = Field(default_factory=list)
    cutoff: datetime | None = None
    version: str = "threat-context-v1"


class FusionResult(BaseModel):
    model_score_id: str = ""
    scope_id: str = "LIVE"
    asset_id: str
    feature_window_id: str
    feature_revision: int
    model_version: str
    base_model_version: str = "fusion-v2"
    fusion_policy_version: str = "fusion-policy-v1"
    enrichment_profile: EnrichmentProfile = EnrichmentProfile.base
    fusion_revision: int = Field(default=1, ge=1)
    evidence_cutoff: datetime | None = None
    input_snapshot_ids: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str = ""
    market_score: float | None
    social_score: float | None
    coordination_score: float | None
    temporal_score: float | None
    claim_risk: float | None
    legitimate_event_score: float | None
    graph_score: float | None
    threat_context: ThreatContext = Field(default_factory=ThreatContext)
    market_anomaly_risk: float | None = Field(default=None, ge=0, le=1)
    market_anomaly_severity: RiskLevel
    social_coordination_risk: float | None = Field(default=None, ge=0, le=1)
    social_coordination_severity: RiskLevel
    raw_cross_domain_risk: float = Field(ge=0, le=1)
    context_adjusted_risk: float = Field(ge=0, le=1)
    fusion_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    severity: RiskLevel
    missing_outputs: list[MissingOutput]
    is_calibrated: bool
    market_regime: str
    market_regime_confidence: float = Field(ge=0, le=1)
    liquidity_class: str
    liquidity_confidence: float = Field(ge=0, le=1)
    stage_signals: dict[str, float | None]
    decision_trace: DecisionTrace
    scored_at: datetime


class ScoreRepository(Protocol):
    async def persist(self, result: FusionResult) -> bool: ...


class ThreatContextRepository(Protocol):
    async def threat_context(
        self,
        scope_id: str,
        asset_id: str,
        cutoff: datetime,
        *,
        enabled: bool,
        freshness_seconds: int,
    ) -> ThreatContext: ...


class ScoreCalibrator(Protocol):
    def calibrate(self, score: float, *, market_regime: str, liquidity_class: str) -> float: ...


class FusionEngine:
    version = "fusion-v2"
    policy_version = "fusion-policy-v1"

    def __init__(
        self,
        *,
        weights: FusionWeights | None = None,
        thresholds: ThresholdConfig | None = None,
        calibrator: ScoreCalibrator | None = None,
        threat_uplift_cap: float = 0.10,
    ) -> None:
        self._weights = weights or FusionWeights()
        self._thresholds = thresholds or ThresholdConfig()
        self._calibrator = calibrator
        self._threat_uplift_cap = threat_uplift_cap

    def fuse(
        self,
        snapshot: FeatureSnapshot,
        outputs: list[DetectorOutput],
        *,
        claim_risk: float | None = None,
        legitimate_event_score: float | None = None,
        graph_score: float | None = None,
        threat_context: ThreatContext | None = None,
        market_regime: str,
        market_regime_confidence: float,
        liquidity_class: str,
        liquidity_confidence: float,
    ) -> FusionResult:
        detector_outputs = {output.name: output for output in outputs}
        detector_values = {name: output.score for name, output in detector_outputs.items()}
        detector_values["claim_risk"] = claim_risk
        detector_values["graph_score"] = graph_score
        weighted_sum = 0.0
        available_weight = 0.0
        for name, weight in self._weights.model_dump().items():
            value = detector_values.get(name)
            if value is not None:
                weighted_sum += float(weight) * float(value)
                available_weight += float(weight)
        raw_weighted_score = weighted_sum / available_weight if available_weight else 0.0
        components = []
        for name, configured_weight in self._weights.model_dump().items():
            value = detector_values.get(name)
            effective_weight = (
                float(configured_weight) / available_weight if value is not None else 0.0
            )
            contribution = float(value) * effective_weight if value is not None else 0.0
            output = detector_outputs.get(name)
            components.append(
                TraceComponent(
                    name=name,
                    value=float(value) if value is not None else None,
                    configured_weight=float(configured_weight),
                    effective_normalized_weight=effective_weight,
                    signed_weighted_contribution=contribution,
                    direction=(
                        ContributionDirection.risk_increasing
                        if contribution > 0
                        else ContributionDirection.neutral
                    ),
                    missing=value is None,
                    missing_reason=(
                        (output.missing_reason or MissingReason.no_observations)
                        if output is not None and value is None
                        else (MissingReason.not_provided if value is None else None)
                    ),
                )
            )
        raw_score = raw_weighted_score
        market_score = detector_values.get("market_score")
        corroborating_scores = [
            detector_values.get("social_score"),
            detector_values.get("coordination_score"),
            detector_values.get("temporal_score"),
            claim_risk,
            graph_score,
        ]
        corroborated = any(value is not None and value >= 0.55 for value in corroborating_scores)
        missing = [
            MissingOutput(
                name=name,
                reason=(
                    detector_outputs[name].missing_reason or MissingReason.no_observations
                    if name in detector_outputs
                    else MissingReason.not_provided
                ),
            )
            for name in (
                "market_score",
                "social_score",
                "coordination_score",
                "temporal_score",
            )
            if detector_values.get(name) is None
        ]
        if claim_risk is None:
            missing.append(MissingOutput(name="claim_risk", reason=MissingReason.not_provided))
        if legitimate_event_score is None:
            missing.append(
                MissingOutput(
                    name="legitimate_event_score",
                    reason=MissingReason.not_provided,
                )
            )
        if graph_score is None:
            missing.append(MissingOutput(name="graph_score", reason=MissingReason.not_provided))
        availability = 1.0 - len(missing) / 7.0
        baseline_confidence = float(snapshot.features["baseline_confidence"] or 0.0)
        data_quality = float(snapshot.features["data_quality_score"] or 0.0)
        confidence = max(
            0.0,
            min(1.0, availability * (0.4 + 0.35 * baseline_confidence + 0.25 * data_quality)),
        )
        raw_score = max(0.0, min(1.0, raw_score))
        is_calibrated = self._calibrator is not None and baseline_confidence >= 0.5
        adjustments: list[ScoreAdjustment] = []
        if is_calibrated and self._calibrator is not None:
            before_calibration = raw_score
            raw_score = max(
                0.0,
                min(
                    1.0,
                    self._calibrator.calibrate(
                        raw_score,
                        market_regime=market_regime,
                        liquidity_class=liquidity_class,
                    ),
                ),
            )
            adjustments.append(
                ScoreAdjustment(
                    name="calibration",
                    before=before_calibration,
                    delta=raw_score - before_calibration,
                    after=raw_score,
                    direction=_direction(raw_score - before_calibration),
                )
            )
        legitimate_adjustment = 1.0 - 0.35 * max(0.0, min(1.0, legitimate_event_score or 0.0))
        adjusted_score = raw_score * legitimate_adjustment
        adjustments.append(
            ScoreAdjustment(
                name="legitimate_event",
                before=raw_score,
                factor=legitimate_adjustment,
                delta=adjusted_score - raw_score,
                after=adjusted_score,
                direction=_direction(adjusted_score - raw_score),
            )
        )
        threat_context = threat_context or ThreatContext()
        threat_before = adjusted_score
        if (
            threat_context.status == ThreatContextStatus.matched
            and threat_context.score is not None
        ):
            uplift = min(
                self._threat_uplift_cap,
                threat_context.score * (threat_context.confidence or 0.0) * self._threat_uplift_cap,
            )
            adjusted_score = min(1.0, adjusted_score + uplift)
            adjustments.append(
                ScoreAdjustment(
                    name="threat_intelligence_uplift",
                    before=threat_before,
                    delta=adjusted_score - threat_before,
                    after=adjusted_score,
                    direction=ContributionDirection.risk_increasing,
                )
            )
        elif threat_context.status in {ThreatContextStatus.unavailable, ThreatContextStatus.stale}:
            confidence *= 0.85
        policies: list[PolicyDecision] = []
        if (
            market_score is not None
            and market_score >= 0.65
            and detector_values.get("coordination_score") is not None
            and float(detector_values["coordination_score"] or 0.0) >= 0.65
        ):
            before = adjusted_score
            adjusted_score = max(adjusted_score, self._thresholds.watch)
            policies.append(
                PolicyDecision(
                    policy="corroborated_watch_floor",
                    applied=True,
                    before=before,
                    after=adjusted_score,
                    reason="market and coordination scores are at least 0.65",
                )
            )
        if market_score is None or market_score < 0.35:
            before = adjusted_score
            adjusted_score = min(adjusted_score, self._thresholds.high - 0.01)
            policies.append(
                PolicyDecision(
                    policy="market_evidence_high_cap",
                    applied=before != adjusted_score,
                    before=before,
                    after=adjusted_score,
                    reason="market score is missing or below 0.35",
                )
            )
        else:
            policies.append(
                PolicyDecision(
                    policy="market_evidence_high_cap",
                    applied=False,
                    before=adjusted_score,
                    after=adjusted_score,
                    reason="market score meets the 0.35 evidence requirement",
                )
            )
        if (
            threat_context.status == ThreatContextStatus.matched
            and threat_before < self._thresholds.high
        ):
            before = adjusted_score
            adjusted_score = min(adjusted_score, self._thresholds.high - 0.01)
            policies.append(
                PolicyDecision(
                    policy="threat_cannot_independently_raise_high",
                    applied=before != adjusted_score,
                    before=before,
                    after=adjusted_score,
                    reason="threat context is corroborating evidence only",
                )
            )

        social_values = [
            (detector_values.get("social_score"), 0.30),
            (detector_values.get("coordination_score"), 0.70),
        ]
        social_weight = sum(weight for value, weight in social_values if value is not None)
        social_coordination_risk = (
            sum(float(value) * weight for value, weight in social_values if value is not None)
            / social_weight
            if social_weight
            else None
        )
        market_anomaly_risk = float(market_score) if market_score is not None else None
        severity = self._severity(adjusted_score)
        if severity == RiskLevel.critical and not (
            market_score is not None and market_score >= 0.65 and corroborated and confidence >= 0.4
        ):
            policies.append(
                PolicyDecision(
                    policy="critical_requires_corroboration",
                    applied=True,
                    before=adjusted_score,
                    after=adjusted_score,
                    reason="severity demoted from CRITICAL to HIGH",
                )
            )
            severity = RiskLevel.high
        if market_score is None and severity in {RiskLevel.high, RiskLevel.critical}:
            policies.append(
                PolicyDecision(
                    policy="missing_market_severity_demotion",
                    applied=True,
                    before=adjusted_score,
                    after=adjusted_score,
                    reason="severity demoted to WATCH because market score is missing",
                )
            )
            severity = RiskLevel.watch
        has_graph = graph_score is not None
        has_verification = claim_risk is not None or legitimate_event_score is not None
        if has_graph and has_verification:
            enrichment_profile = EnrichmentProfile.graph_and_verification
            fusion_revision = 3
        elif has_graph:
            enrichment_profile = EnrichmentProfile.graph
            fusion_revision = 2
        elif has_verification:
            enrichment_profile = EnrichmentProfile.verification
            fusion_revision = 2
        else:
            enrichment_profile = EnrichmentProfile.base
            fusion_revision = 1
        return FusionResult(
            scope_id=snapshot.scope_id,
            asset_id=snapshot.asset_id,
            feature_window_id=str(snapshot.feature_window_id),
            feature_revision=snapshot.revision,
            model_version=self.version,
            base_model_version=self.version,
            fusion_policy_version=self.policy_version,
            enrichment_profile=enrichment_profile,
            fusion_revision=fusion_revision,
            evidence_cutoff=snapshot.window_end,
            market_score=market_score,
            social_score=detector_values.get("social_score"),
            coordination_score=detector_values.get("coordination_score"),
            temporal_score=detector_values.get("temporal_score"),
            claim_risk=claim_risk,
            legitimate_event_score=legitimate_event_score,
            graph_score=graph_score,
            threat_context=threat_context,
            market_anomaly_risk=market_anomaly_risk,
            market_anomaly_severity=self._severity(market_anomaly_risk or 0.0),
            social_coordination_risk=social_coordination_risk,
            social_coordination_severity=self._severity(social_coordination_risk or 0.0),
            raw_cross_domain_risk=raw_score,
            context_adjusted_risk=adjusted_score,
            fusion_score=adjusted_score,
            confidence=confidence,
            severity=severity,
            missing_outputs=missing,
            is_calibrated=is_calibrated,
            market_regime=market_regime,
            market_regime_confidence=market_regime_confidence,
            liquidity_class=liquidity_class,
            liquidity_confidence=liquidity_confidence,
            stage_signals={
                "price_return": _optional_float(snapshot.features["price_return"]),
                "relative_volume": _optional_float(snapshot.features["relative_volume"]),
                "spread": _optional_float(snapshot.features["spread"]),
                "orderbook_imbalance": _optional_float(snapshot.features["orderbook_imbalance"]),
                "buy_sell_pressure": _optional_float(snapshot.features["buy_sell_pressure"]),
                "mention_count": _optional_float(snapshot.features["mention_count"]),
            },
            decision_trace=DecisionTrace(
                components=components,
                adjustments=adjustments,
                policy_decisions=policies,
                thresholds=self._thresholds,
                raw_weighted_score=raw_weighted_score,
                final_score=adjusted_score,
            ),
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
        threat_repository: ThreatContextRepository | None = None,
        threat_enabled: bool = False,
        threat_freshness_seconds: int = 86400,
    ) -> None:
        self._repository = repository
        self._state = state
        self._publisher = publisher
        self._fusion = fusion or FusionEngine()
        self._threat_repository = threat_repository
        self._threat_enabled = threat_enabled
        self._threat_freshness_seconds = threat_freshness_seconds
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
        graph_score: float | None = None,
        graph_snapshot_id: str | None = None,
        verification_snapshot_id: str | None = None,
        threat_context: ThreatContext | None = None,
    ) -> FusionResult:
        if threat_context is None and self._threat_repository is not None:
            threat_context = await self._threat_repository.threat_context(
                snapshot.scope_id,
                snapshot.asset_id,
                snapshot.window_end,
                enabled=self._threat_enabled,
                freshness_seconds=self._threat_freshness_seconds,
            )
        outputs = [
            self._market.score(snapshot),
            self._social.score(snapshot),
            self._coordination.score(snapshot),
            self._temporal.score(snapshot),
        ]
        regime, regime_confidence = self._regime.classify(snapshot)
        liquidity, liquidity_confidence = self._liquidity.classify(snapshot)
        result = self._fusion.fuse(
            snapshot,
            outputs,
            claim_risk=claim_risk,
            legitimate_event_score=legitimate_event_score,
            graph_score=graph_score,
            threat_context=threat_context,
            market_regime=regime.value,
            market_regime_confidence=regime_confidence,
            liquidity_class=liquidity.value,
            liquidity_confidence=liquidity_confidence,
        )
        input_snapshot_ids = {
            key: value
            for key, value in {
                "graph_snapshot_id": graph_snapshot_id,
                "verification_snapshot_id": verification_snapshot_id,
                "threat_snapshot_id": threat_context.snapshot_id if threat_context else None,
            }.items()
            if value is not None
        }
        identity = {
            "scope_id": snapshot.scope_id,
            "asset_id": snapshot.asset_id,
            "feature_window_id": str(snapshot.feature_window_id),
            "feature_revision": snapshot.revision,
            "enrichment_profile": result.enrichment_profile.value,
            "input_snapshot_ids": input_snapshot_ids,
            "fusion_policy_version": result.fusion_policy_version,
        }
        idempotency_key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        model_score_id = str(uuid5(NAMESPACE_URL, f"model-score:{idempotency_key}"))
        result = result.model_copy(
            update={
                "model_score_id": model_score_id,
                "input_snapshot_ids": input_snapshot_ids,
                "idempotency_key": idempotency_key,
            }
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
                        f"{snapshot.revision}:{result.idempotency_key}",
                    )
                ),
                event_type=EventType.model_fusion_scored,
                schema_version=1,
                source=result.base_model_version,
                source_event_id=(
                    f"{snapshot.scope_id}:{snapshot.feature_window_id}:"
                    f"{snapshot.revision}:{result.idempotency_key}"
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


def _optional_float(value: float | int | None) -> float | None:
    return float(value) if value is not None else None


def _direction(delta: float) -> ContributionDirection:
    if delta > 0:
        return ContributionDirection.risk_increasing
    if delta < 0:
        return ContributionDirection.risk_reducing
    return ContributionDirection.neutral


class InMemoryScoreRepository:
    def __init__(self) -> None:
        self.results: dict[tuple[str, int, str], FusionResult] = {}

    async def persist(self, result: FusionResult) -> bool:
        key = (result.feature_window_id, result.feature_revision, result.idempotency_key)
        if key in self.results:
            return False
        self.results[key] = result
        return True
