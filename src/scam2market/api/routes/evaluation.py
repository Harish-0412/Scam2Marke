import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import (
    AuditLogModel,
    ModelAliasModel,
    ModelArtifactModel,
    ReplaySessionModel,
)
from scam2market.db.session import AsyncSessionLocal, get_db_session
from scam2market.evaluation.mlflow import MlflowTrackingClient
from scam2market.evaluation.repository import EvaluationRepository
from scam2market.evaluation.schemas import (
    AliasAssignment,
    ModelArtifactCreate,
    ReplayCreate,
    ShadowScoreRequest,
)
from scam2market.ingestion.scenarios import load_scenario_manifest
from scam2market.security.auth import CurrentPrincipal

router = APIRouter()


@router.post("/replays", status_code=201)
async def create_replay(
    body: ReplayCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        manifest = load_scenario_manifest(f"{body.scenario_id}.yaml")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail="unknown replay scenario") from exc
    replay_id = uuid4()
    scope_id = str(replay_id)
    manifest_hash = hashlib.sha256(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    replay = ReplaySessionModel(
        tenant_id=principal.tenant_id,
        replay_session_id=replay_id,
        scope_id=scope_id,
        dataset_id=manifest.scenario_id,
        scenario_version=manifest.scenario_version,
        manifest_hash=manifest_hash,
        random_seed=body.random_seed if body.random_seed is not None else manifest.seed,
        speed_multiplier=body.speed_multiplier,
        status="CREATED",
        requested_by=actor_id,
        configuration_json={
            **body.configuration,
            "isolation": {"scope_id": scope_id, "publishes_to_live": False},
        },
    )
    session.add(replay)
    await session.commit()
    await session.refresh(replay)
    return _replay_response(replay)


@router.get("/replays")
async def list_replays(
    principal: CurrentPrincipal,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(ReplaySessionModel).where(ReplaySessionModel.tenant_id == principal.tenant_id)
    if status is not None:
        query = query.where(ReplaySessionModel.status == status.upper())
    rows = (
        await session.scalars(query.order_by(ReplaySessionModel.created_at.desc()).limit(limit))
    ).all()
    return [_replay_response(row) for row in rows]


@router.get("/replays/{replay_session_id}")
async def get_replay(
    replay_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    replay = await session.get(ReplaySessionModel, replay_session_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="replay not found")
    return _replay_response(replay)


@router.post("/replays/{replay_session_id}/start", status_code=202)
async def start_replay(
    replay_session_id: UUID,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    replay = await session.get(ReplaySessionModel, replay_session_id, with_for_update=True)
    if replay is None:
        raise HTTPException(status_code=404, detail="replay not found")
    if replay.status not in {"CREATED", "PAUSED"}:
        raise HTTPException(status_code=409, detail=f"replay cannot start from {replay.status}")
    replay.status = "QUEUED"
    replay.paused_at = None
    replay.configuration_json = {
        **replay.configuration_json,
        "control": {"requested_action": "START", "requested_by": actor_id},
    }
    session.add(
        AuditLogModel(
            tenant_id=replay.tenant_id,
            actor_id=actor_id,
            action="START_REPLAY",
            target_type="REPLAY_SESSION",
            target_id=str(replay_session_id),
        )
    )
    await session.commit()
    return _replay_response(replay)


@router.post("/replays/{replay_session_id}/pause")
async def pause_replay(
    replay_session_id: UUID,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    replay = await session.get(ReplaySessionModel, replay_session_id, with_for_update=True)
    if replay is None:
        raise HTTPException(status_code=404, detail="replay not found")
    if replay.status not in {"QUEUED", "RUNNING"}:
        raise HTTPException(status_code=409, detail=f"replay cannot pause from {replay.status}")
    replay.status = "PAUSED"
    replay.paused_at = datetime.now(tz=UTC)
    replay.configuration_json = {
        **replay.configuration_json,
        "control": {"requested_action": "PAUSE", "requested_by": actor_id},
    }
    session.add(
        AuditLogModel(
            tenant_id=replay.tenant_id,
            actor_id=actor_id,
            action="PAUSE_REPLAY",
            target_type="REPLAY_SESSION",
            target_id=str(replay_session_id),
        )
    )
    await session.commit()
    return _replay_response(replay)


@router.post("/replays/{replay_session_id}/evaluate")
async def evaluate_replay(replay_session_id: UUID) -> dict[str, Any]:
    repository = EvaluationRepository(AsyncSessionLocal)
    try:
        evaluation = await repository.evaluate(replay_session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    settings = get_settings()
    if settings.mlflow_enabled and evaluation.mlflow_run_id is None:
        run_id = await MlflowTrackingClient(
            str(settings.mlflow_tracking_uri), timeout_seconds=settings.mlflow_timeout_seconds
        ).log_evaluation(evaluation)
        if run_id is not None:
            await repository.set_mlflow_run(evaluation.evaluation_id, run_id)
            evaluation = evaluation.model_copy(update={"mlflow_run_id": run_id})
    return evaluation.model_dump(mode="json")


@router.post("/models/artifacts", status_code=201)
async def register_model_artifact(
    body: ModelArtifactCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    artifact_id = uuid5(
        NAMESPACE_URL,
        f"model-artifact:{body.model_family}:{body.model_version}:{body.artifact_hash}",
    )
    existing = await session.get(ModelArtifactModel, artifact_id)
    if existing is not None:
        return _artifact_response(existing)
    artifact = ModelArtifactModel(
        model_artifact_id=artifact_id,
        model_family=body.model_family,
        model_version=body.model_version,
        artifact_uri=body.artifact_uri,
        artifact_hash=body.artifact_hash.lower(),
        input_schema_hash=body.input_schema_hash.lower(),
        training_data_hash=(body.training_data_hash.lower() if body.training_data_hash else None),
        mlflow_run_id=body.mlflow_run_id,
        metadata_json=body.metadata,
    )
    session.add(artifact)
    session.add(
        AuditLogModel(
            actor_id=actor_id,
            action="REGISTER_MODEL_ARTIFACT",
            target_type="MODEL_ARTIFACT",
            target_id=str(artifact_id),
            metadata_json={"family": body.model_family, "version": body.model_version},
        )
    )
    await session.commit()
    await session.refresh(artifact)
    return _artifact_response(artifact)


@router.put("/models/{model_family}/aliases/{alias}")
async def assign_model_alias(
    model_family: str,
    alias: str,
    body: AliasAssignment,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    normalized_alias = alias.upper()
    if normalized_alias not in {"CHAMPION", "CANDIDATE", "SHADOW"}:
        raise HTTPException(status_code=422, detail="alias must be CHAMPION, CANDIDATE, or SHADOW")
    artifact = await session.get(ModelArtifactModel, body.model_artifact_id)
    if artifact is None or artifact.model_family != model_family:
        raise HTTPException(status_code=422, detail="artifact does not belong to model family")
    assignment = await session.get(ModelAliasModel, (model_family, normalized_alias))
    old_artifact_id = assignment.model_artifact_id if assignment is not None else None
    if assignment is None:
        assignment = ModelAliasModel(
            model_family=model_family,
            alias=normalized_alias,
            model_artifact_id=body.model_artifact_id,
            assigned_by=actor_id,
            reason=body.reason,
        )
        session.add(assignment)
    else:
        assignment.model_artifact_id = body.model_artifact_id
        assignment.assigned_by = actor_id
        assignment.reason = body.reason
        assignment.assigned_at = datetime.now(tz=UTC)
    session.add(
        AuditLogModel(
            actor_id=actor_id,
            action="ASSIGN_MODEL_ALIAS",
            target_type="MODEL_ALIAS",
            target_id=f"{model_family}:{normalized_alias}",
            reason=body.reason,
            metadata_json={
                "old_artifact_id": str(old_artifact_id) if old_artifact_id else None,
                "new_artifact_id": str(body.model_artifact_id),
            },
        )
    )
    await session.commit()
    return {
        "model_family": assignment.model_family,
        "alias": assignment.alias,
        "model_artifact_id": str(assignment.model_artifact_id),
        "assigned_by": assignment.assigned_by,
        "reason": assignment.reason,
        "assigned_at": assignment.assigned_at,
    }


@router.post("/shadow-scores", status_code=201)
async def run_shadow_score(body: ShadowScoreRequest) -> dict[str, Any]:
    repository = EvaluationRepository(AsyncSessionLocal)
    try:
        score = await repository.shadow_score(
            model_artifact_id=body.model_artifact_id,
            feature_window_id=body.feature_window_id,
            feature_revision=body.feature_revision,
            latency_ms=body.latency_ms,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "shadow_score_id": str(score.shadow_score_id),
        "model_artifact_id": str(score.model_artifact_id),
        "feature_window_id": str(score.feature_window_id),
        "feature_revision": score.feature_revision,
        "score": score.score,
        "severity": score.severity,
        "confidence": score.confidence,
        "agreement": score.agreement,
        "controls_alerts": score.controls_alerts,
        "latency_ms": score.latency_ms,
        "scored_at": score.scored_at,
    }


def _replay_response(replay: ReplaySessionModel) -> dict[str, Any]:
    return {
        "replay_session_id": str(replay.replay_session_id),
        "scope_id": replay.scope_id,
        "dataset_id": replay.dataset_id,
        "scenario_version": replay.scenario_version,
        "manifest_hash": replay.manifest_hash,
        "random_seed": replay.random_seed,
        "speed_multiplier": replay.speed_multiplier,
        "status": replay.status,
        "virtual_clock_at": replay.virtual_clock_at,
        "paused_at": replay.paused_at,
        "requested_by": replay.requested_by,
        "configuration": replay.configuration_json,
        "failure_reason": replay.failure_reason,
        "started_at": replay.started_at,
        "completed_at": replay.completed_at,
        "created_at": replay.created_at,
    }


def _artifact_response(artifact: ModelArtifactModel) -> dict[str, Any]:
    return {
        "model_artifact_id": str(artifact.model_artifact_id),
        "model_family": artifact.model_family,
        "model_version": artifact.model_version,
        "artifact_uri": artifact.artifact_uri,
        "artifact_hash": artifact.artifact_hash,
        "input_schema_hash": artifact.input_schema_hash,
        "training_data_hash": artifact.training_data_hash,
        "mlflow_run_id": artifact.mlflow_run_id,
        "status": artifact.status,
        "metadata": artifact.metadata_json,
        "created_at": artifact.created_at,
    }
