from datetime import UTC, datetime
from statistics import fmean
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    AblationResultModel,
    FeatureRevisionModel,
    FeatureWindowModel,
    ModelArtifactModel,
    ModelScoreModel,
    ReplayEvaluationModel,
    ReplaySessionModel,
    ShadowScoreModel,
)
from scam2market.evaluation.schemas import ReplayEvaluation, ScoreObservation
from scam2market.evaluation.service import ReplayEvaluator, _severity, shadow_fusion_score
from scam2market.ingestion.scenarios import load_scenario_manifest


class EvaluationRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        evaluator: ReplayEvaluator | None = None,
    ) -> None:
        self._sessions = sessions
        self._evaluator = evaluator or ReplayEvaluator()

    async def evaluate(self, replay_session_id: UUID) -> ReplayEvaluation:
        async with self._sessions() as session, session.begin():
            replay = await session.get(ReplaySessionModel, replay_session_id)
            if replay is None:
                raise LookupError(f"replay {replay_session_id} not found")
            existing = await session.scalar(
                select(ReplayEvaluationModel).where(
                    ReplayEvaluationModel.replay_session_id == replay_session_id,
                    ReplayEvaluationModel.evaluation_version == "replay-evaluation-v1",
                )
            )
            if existing is not None:
                return await self._load(session, existing)
            rows = (
                await session.execute(
                    select(ModelScoreModel, FeatureRevisionModel)
                    .join(
                        FeatureWindowModel,
                        FeatureWindowModel.feature_window_id == ModelScoreModel.feature_window_id,
                    )
                    .join(
                        FeatureRevisionModel,
                        (
                            FeatureRevisionModel.feature_window_id
                            == ModelScoreModel.feature_window_id
                        )
                        & (FeatureRevisionModel.revision == ModelScoreModel.feature_revision),
                    )
                    .where(FeatureWindowModel.scope_id == replay.scope_id)
                    .order_by(ModelScoreModel.evidence_cutoff, ModelScoreModel.fusion_revision)
                )
            ).all()
            if not rows:
                raise ValueError("replay has no model scores to evaluate")
            observations = [self._observation(score, revision) for score, revision in rows]
            scenario = load_scenario_manifest(f"{replay.dataset_id}.yaml")
            positive_from = scenario.timeline["expected_volume_anomaly"]
            evaluation = self._evaluator.evaluate(
                replay_session_id=replay_session_id,
                manifest_hash=replay.manifest_hash,
                observations=observations,
                positive_from=positive_from,
                generated_at=datetime.now(tz=UTC),
            )
            session.add(
                ReplayEvaluationModel(
                    evaluation_id=evaluation.evaluation_id,
                    replay_session_id=evaluation.replay_session_id,
                    evaluation_version=evaluation.evaluation_version,
                    status="COMPLETED",
                    manifest_hash=evaluation.manifest_hash,
                    metrics_json=evaluation.metrics.model_dump(mode="json"),
                    generated_at=evaluation.generated_at,
                )
            )
            await session.flush()
            session.add_all(
                [
                    AblationResultModel(
                        ablation_result_id=uuid5(
                            NAMESPACE_URL,
                            f"ablation:{evaluation.evaluation_id}:{ablation.profile}",
                        ),
                        evaluation_id=evaluation.evaluation_id,
                        profile=ablation.profile,
                        component_set_json=ablation.components,
                        metrics_json=ablation.metrics.model_dump(mode="json"),
                        contribution_delta=ablation.contribution_delta,
                        generated_at=evaluation.generated_at,
                    )
                    for ablation in evaluation.ablations
                ]
            )
            return evaluation

    async def set_mlflow_run(self, evaluation_id: UUID, run_id: str) -> None:
        async with self._sessions.begin() as session:
            evaluation = await session.get(ReplayEvaluationModel, evaluation_id)
            if evaluation is not None:
                evaluation.mlflow_run_id = run_id

    async def shadow_score(
        self,
        *,
        model_artifact_id: UUID,
        feature_window_id: UUID,
        feature_revision: int,
        latency_ms: float,
    ) -> ShadowScoreModel:
        async with self._sessions() as session, session.begin():
            artifact = await session.get(ModelArtifactModel, model_artifact_id)
            if artifact is None:
                raise LookupError(f"model artifact {model_artifact_id} not found")
            revision = await session.get(
                FeatureRevisionModel, (feature_window_id, feature_revision)
            )
            if revision is None:
                raise LookupError("feature revision not found")
            champion = await session.scalar(
                select(ModelScoreModel)
                .where(
                    ModelScoreModel.feature_window_id == feature_window_id,
                    ModelScoreModel.feature_revision == feature_revision,
                )
                .order_by(ModelScoreModel.fusion_revision.desc())
                .limit(1)
            )
            if champion is None:
                raise ValueError("champion score is required for shadow comparison")
            existing = await session.scalar(
                select(ShadowScoreModel).where(
                    ShadowScoreModel.feature_window_id == feature_window_id,
                    ShadowScoreModel.feature_revision == feature_revision,
                    ShadowScoreModel.model_artifact_id == model_artifact_id,
                )
            )
            if existing is not None:
                return existing
            components = _components(champion)
            raw_weights = artifact.metadata_json.get("weights", {})
            weights = (
                {str(name): float(value) for name, value in raw_weights.items()}
                if isinstance(raw_weights, dict) and raw_weights
                else {
                    "market_score": 0.40,
                    "social_score": 0.10,
                    "coordination_score": 0.18,
                    "temporal_score": 0.10,
                    "claim_risk": 0.12,
                    "graph_score": 0.10,
                }
            )
            score = shadow_fusion_score(components, weights)
            severity = _severity(score)
            window = await session.get(FeatureWindowModel, feature_window_id)
            replay_id = None
            if window is not None and window.scope_id != "LIVE":
                try:
                    replay_id = UUID(window.scope_id)
                except ValueError:
                    replay_id = None
            shadow = ShadowScoreModel(
                shadow_score_id=uuid5(
                    NAMESPACE_URL,
                    f"shadow:{feature_window_id}:{feature_revision}:{model_artifact_id}",
                ),
                replay_session_id=replay_id,
                feature_window_id=feature_window_id,
                feature_revision=feature_revision,
                model_artifact_id=model_artifact_id,
                champion_model_score_id=champion.model_score_id,
                score=score,
                severity=severity,
                confidence=max(
                    0.0,
                    min(
                        1.0,
                        champion.confidence * (1 - len(champion.missing_outputs_json) / 7),
                    ),
                ),
                controls_alerts=False,
                agreement=severity == champion.severity,
                latency_ms=latency_ms,
                scored_at=datetime.now(tz=UTC),
            )
            session.add(shadow)
            return shadow

    @staticmethod
    def _observation(score: ModelScoreModel, revision: FeatureRevisionModel) -> ScoreObservation:
        market_freshness = revision.features_json.get("market_data_freshness_seconds")
        social_freshness = revision.features_json.get("social_data_freshness_seconds")
        freshness_values = [
            float(value) for value in (market_freshness, social_freshness) if value is not None
        ]
        processing_latency_ms = max(
            0.0, (score.scored_at - revision.created_at).total_seconds() * 1000
        )
        return ScoreObservation(
            score_id=score.model_score_id,
            event_time=score.evidence_cutoff,
            scored_at=score.scored_at,
            severity=score.severity,
            confidence=score.confidence,
            components=_components(score),
            missing_output_count=len(score.missing_outputs_json),
            data_freshness_seconds=(fmean(freshness_values) if freshness_values else None),
            processing_latency_ms=processing_latency_ms,
        )

    @staticmethod
    async def _load(session: AsyncSession, row: ReplayEvaluationModel) -> ReplayEvaluation:
        ablations = (
            await session.scalars(
                select(AblationResultModel)
                .where(AblationResultModel.evaluation_id == row.evaluation_id)
                .order_by(AblationResultModel.generated_at, AblationResultModel.profile)
            )
        ).all()
        return ReplayEvaluation.model_validate(
            {
                "evaluation_id": row.evaluation_id,
                "replay_session_id": row.replay_session_id,
                "evaluation_version": row.evaluation_version,
                "manifest_hash": row.manifest_hash,
                "metrics": row.metrics_json,
                "ablations": [
                    {
                        "profile": item.profile,
                        "components": item.component_set_json,
                        "metrics": item.metrics_json,
                        "contribution_delta": item.contribution_delta,
                    }
                    for item in ablations
                ],
                "generated_at": row.generated_at,
                "mlflow_run_id": row.mlflow_run_id,
            }
        )


def _components(score: ModelScoreModel) -> dict[str, float | None]:
    return {
        "market_score": score.market_score,
        "social_score": score.social_score,
        "coordination_score": score.coordination_score,
        "temporal_score": score.temporal_score,
        "claim_risk": score.claim_risk,
        "legitimate_event_score": score.legitimate_event_score,
        "graph_score": score.graph_score,
    }
