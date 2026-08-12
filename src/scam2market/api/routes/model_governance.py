from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import (
    AuditLogModel,
    CalibrationLabelModel,
    FalsePositiveReportModel,
    ModelAliasModel,
    ModelArtifactModel,
    ModelCalibrationModel,
    ModelDriftEventModel,
    ModelPromotionDecisionModel,
)
from scam2market.db.session import get_db_session
from scam2market.model_governance.calibration import (
    calibration_metrics,
    fit_platt_calibration,
    promotion_checks,
)
from scam2market.security.auth import CurrentPrincipal

router = APIRouter()


class CalibrationLabelCreate(BaseModel):
    model_family: str = Field(min_length=2, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    raw_score: float = Field(ge=0, le=1)
    outcome: bool
    data_partition: Literal["CALIBRATION", "HOLDOUT"] = "CALIBRATION"
    segment: dict[str, str] = Field(default_factory=dict)
    alert_id: UUID | None = None
    event_time: datetime
    reason: str = Field(min_length=5, max_length=2000)


class CalibrationFitRequest(BaseModel):
    model_artifact_id: UUID
    segment: dict[str, str] = Field(default_factory=dict)


class PromotionRequest(BaseModel):
    candidate_artifact_id: UUID
    reason: str = Field(min_length=5, max_length=2000)
    apply_alias: bool = False


class FalsePositiveCreate(BaseModel):
    alert_id: UUID | None = None
    model_family: str = Field(min_length=2, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    asset_id: str | None = Field(default=None, max_length=64)
    reason_code: Literal[
        "LEGITIMATE_EVENT",
        "ASSET_AMBIGUITY",
        "DATA_QUALITY",
        "THRESHOLD_TOO_LOW",
        "DUPLICATE_CAMPAIGN",
        "OTHER",
    ]
    notes: str = Field(min_length=5, max_length=4000)


@router.post("/model-governance/labels", status_code=201)
async def create_calibration_label(
    body: CalibrationLabelCreate,
    principal: CurrentPrincipal,
    actor_id: str = Header(alias="X-Actor-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = CalibrationLabelModel(
        tenant_id=principal.tenant_id,
        model_family=body.model_family,
        model_version=body.model_version,
        raw_score=body.raw_score,
        outcome=body.outcome,
        data_partition=body.data_partition,
        segment_json=body.segment,
        alert_id=body.alert_id,
        event_time=body.event_time,
        labeled_by=actor_id,
        label_reason=body.reason,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"label_id": str(row.label_id), "created_at": row.created_at}


@router.post("/models/governance/calibrations", status_code=201)
async def fit_calibration(
    body: CalibrationFitRequest,
    principal: CurrentPrincipal,
    actor_id: str = Header(alias="X-Actor-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    artifact = await session.get(ModelArtifactModel, body.model_artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="model artifact not found")
    labels = await _labels(session, principal.tenant_id, artifact, "CALIBRATION", body.segment)
    settings = get_settings()
    try:
        fitted = fit_platt_calibration(labels, minimum_samples=settings.calibration_min_samples)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    holdout = await _labels(session, principal.tenant_id, artifact, "HOLDOUT", body.segment)
    holdout_metrics = None
    if holdout:
        holdout_metrics = calibration_metrics(
            [fitted.predict(score) for score, _ in holdout], [label for _, label in holdout]
        )
    metrics = {
        "fit": asdict(fitted.metrics),
        "holdout": asdict(holdout_metrics) if holdout_metrics else None,
        "holdout_sample_count": len(holdout),
    }
    row = ModelCalibrationModel(
        tenant_id=principal.tenant_id,
        model_artifact_id=artifact.model_artifact_id,
        segment_json=body.segment,
        parameters_json={"slope": fitted.slope, "intercept": fitted.intercept},
        metrics_json=metrics,
        sample_count=fitted.metrics.sample_count,
        data_hash=fitted.data_hash,
        created_by=actor_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _calibration_response(row)


@router.post("/models/governance/promotions", status_code=201)
async def evaluate_promotion(
    body: PromotionRequest,
    principal: CurrentPrincipal,
    actor_id: str = Header(alias="X-Actor-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    candidate = await session.get(ModelArtifactModel, body.candidate_artifact_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate artifact not found")
    calibration = await session.scalar(
        select(ModelCalibrationModel)
        .where(
            ModelCalibrationModel.tenant_id == principal.tenant_id,
            ModelCalibrationModel.model_artifact_id == candidate.model_artifact_id,
            ModelCalibrationModel.status == "ACTIVE",
        )
        .order_by(ModelCalibrationModel.created_at.desc())
        .limit(1)
    )
    if calibration is None:
        raise HTTPException(status_code=409, detail="candidate has no active calibration")
    champion_alias = await session.get(ModelAliasModel, (candidate.model_family, "CHAMPION"))
    champion_id = champion_alias.model_artifact_id if champion_alias else None
    champion_brier = None
    if champion_id is not None and champion_id != candidate.model_artifact_id:
        champion_calibration = await session.scalar(
            select(ModelCalibrationModel)
            .where(
                ModelCalibrationModel.tenant_id == principal.tenant_id,
                ModelCalibrationModel.model_artifact_id == champion_id,
                ModelCalibrationModel.status == "ACTIVE",
            )
            .order_by(ModelCalibrationModel.created_at.desc())
            .limit(1)
        )
        if champion_calibration is not None:
            champion_metrics = (
                champion_calibration.metrics_json.get("holdout")
                or champion_calibration.metrics_json["fit"]
            )
            champion_brier = float(champion_metrics["brier_score"])
    latest_drift = await session.scalar(
        select(ModelDriftEventModel)
        .where(
            ModelDriftEventModel.tenant_id == principal.tenant_id,
            ModelDriftEventModel.model_family == candidate.model_family,
            ModelDriftEventModel.model_version == candidate.model_version,
        )
        .order_by(ModelDriftEventModel.observed_at.desc())
        .limit(1)
    )
    settings = get_settings()
    metrics = calibration.metrics_json.get("holdout") or calibration.metrics_json["fit"]
    false_positives = await session.scalar(
        select(func.count(FalsePositiveReportModel.report_id)).where(
            FalsePositiveReportModel.tenant_id == principal.tenant_id,
            FalsePositiveReportModel.model_family == candidate.model_family,
            FalsePositiveReportModel.model_version == candidate.model_version,
            FalsePositiveReportModel.created_at >= datetime.now(tz=UTC) - timedelta(days=30),
        )
    )
    checks = promotion_checks(
        metrics=metrics,
        sample_count=calibration.sample_count,
        minimum_samples=settings.calibration_min_samples,
        maximum_ece=settings.calibration_max_ece,
        minimum_auc=settings.calibration_min_auc,
        drift_status=latest_drift.status if latest_drift else None,
        false_positive_count=false_positives or 0,
        false_positive_budget=settings.promotion_max_false_positives,
        champion_brier_score=champion_brier,
        brier_tolerance=settings.promotion_brier_tolerance,
        champion_comparison_required=(
            champion_id is not None and champion_id != candidate.model_artifact_id
        ),
    )
    passed = all(checks.values())
    status = "PROMOTED" if passed and body.apply_alias else "APPROVED" if passed else "REJECTED"
    decision = ModelPromotionDecisionModel(
        tenant_id=principal.tenant_id,
        model_family=candidate.model_family,
        candidate_artifact_id=candidate.model_artifact_id,
        champion_artifact_id=champion_id,
        calibration_id=calibration.calibration_id,
        status=status,
        checks_json=checks,
        reason=body.reason,
        decided_by=actor_id,
    )
    session.add(decision)
    if status == "PROMOTED":
        await _promote_alias(session, candidate, actor_id, body.reason)
    session.add(
        AuditLogModel(
            tenant_id=principal.tenant_id,
            actor_id=actor_id,
            action="MODEL_PROMOTION_DECISION",
            target_type="MODEL_ARTIFACT",
            target_id=str(candidate.model_artifact_id),
            reason=body.reason,
            metadata_json={"status": status, "checks": checks},
        )
    )
    await session.commit()
    await session.refresh(decision)
    return _decision_response(decision)


@router.post("/false-positive-reports", status_code=201)
async def create_false_positive_report(
    body: FalsePositiveCreate,
    principal: CurrentPrincipal,
    actor_id: str = Header(alias="X-Actor-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = FalsePositiveReportModel(
        tenant_id=principal.tenant_id,
        alert_id=body.alert_id,
        model_family=body.model_family,
        model_version=body.model_version,
        asset_id=body.asset_id,
        reason_code=body.reason_code,
        notes=body.notes,
        reported_by=actor_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _false_positive_response(row)


@router.get("/false-positive-reports")
async def list_false_positive_reports(
    principal: CurrentPrincipal,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(FalsePositiveReportModel)
            .where(FalsePositiveReportModel.tenant_id == principal.tenant_id)
            .order_by(FalsePositiveReportModel.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_false_positive_response(row) for row in rows]


async def _labels(
    session: AsyncSession,
    tenant_id: str,
    artifact: ModelArtifactModel,
    partition: str,
    segment: dict[str, str],
) -> list[tuple[float, bool]]:
    query = select(CalibrationLabelModel).where(
        CalibrationLabelModel.tenant_id == tenant_id,
        CalibrationLabelModel.model_family == artifact.model_family,
        CalibrationLabelModel.model_version == artifact.model_version,
        CalibrationLabelModel.data_partition == partition,
    )
    if segment:
        query = query.where(CalibrationLabelModel.segment_json == segment)
    rows = (await session.scalars(query.order_by(CalibrationLabelModel.event_time))).all()
    return [(row.raw_score, row.outcome) for row in rows]


async def _promote_alias(
    session: AsyncSession, artifact: ModelArtifactModel, actor_id: str, reason: str
) -> None:
    alias = await session.get(ModelAliasModel, (artifact.model_family, "CHAMPION"))
    if alias is None:
        session.add(
            ModelAliasModel(
                model_family=artifact.model_family,
                alias="CHAMPION",
                model_artifact_id=artifact.model_artifact_id,
                assigned_by=actor_id,
                reason=reason,
            )
        )
        return
    alias.model_artifact_id = artifact.model_artifact_id
    alias.assigned_by = actor_id
    alias.reason = reason
    alias.assigned_at = datetime.now(tz=UTC)


def _calibration_response(row: ModelCalibrationModel) -> dict[str, Any]:
    return {
        "calibration_id": str(row.calibration_id),
        "model_artifact_id": str(row.model_artifact_id),
        "method": row.method,
        "segment": row.segment_json,
        "parameters": row.parameters_json,
        "metrics": row.metrics_json,
        "sample_count": row.sample_count,
        "data_hash": row.data_hash,
        "status": row.status,
        "created_at": row.created_at,
    }


def _decision_response(row: ModelPromotionDecisionModel) -> dict[str, Any]:
    return {
        "decision_id": str(row.decision_id),
        "model_family": row.model_family,
        "candidate_artifact_id": str(row.candidate_artifact_id),
        "champion_artifact_id": str(row.champion_artifact_id) if row.champion_artifact_id else None,
        "status": row.status,
        "checks": row.checks_json,
        "reason": row.reason,
        "decided_by": row.decided_by,
        "created_at": row.created_at,
    }


def _false_positive_response(row: FalsePositiveReportModel) -> dict[str, Any]:
    return {
        "report_id": str(row.report_id),
        "alert_id": str(row.alert_id) if row.alert_id else None,
        "model_family": row.model_family,
        "model_version": row.model_version,
        "asset_id": row.asset_id,
        "reason_code": row.reason_code,
        "notes": row.notes,
        "status": row.status,
        "reported_by": row.reported_by,
        "created_at": row.created_at,
    }
