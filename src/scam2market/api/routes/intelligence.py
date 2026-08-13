from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, exists, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from scam2market.db.models import (
    CampaignModel,
    ModelExplanationModel,
    ModelScoreModel,
    ReplaySessionModel,
    ThreatContextSnapshotModel,
    ThreatFeedStatusModel,
    ThreatIndicatorModel,
    ThreatMatchModel,
    ThreatObservationModel,
)
from scam2market.db.session import get_db_session
from scam2market.intelligence.fusion import DecisionTrace, ThreatContextStatus
from scam2market.security.auth import CurrentPrincipal, Role

router = APIRouter()


class ModelExplanationResponse(BaseModel):
    explanation_id: UUID
    model_score_id: UUID
    method: str
    version: str
    scope_id: str
    status: str
    explanation_hash: str
    generated_at: datetime
    decision_trace: DecisionTrace


class ThreatIndicatorResponse(BaseModel):
    indicator_id: str
    indicator_type: str
    normalized_value: str
    active: bool
    first_seen: datetime
    last_seen: datetime
    tlp: str
    confidence: float


class ThreatContextResponse(BaseModel):
    snapshot_id: UUID
    scope_id: str
    asset_id: str
    cutoff: datetime
    status: ThreatContextStatus
    score: float | None
    confidence: float | None
    match_ids: list[str]
    version: str


class ThreatMatchResponse(BaseModel):
    match_id: UUID
    scope_id: str
    asset_id: str
    post_id: str
    indicator_id: str
    indicator_type: str
    matched_value: str
    match_type: str
    event_time: datetime
    evidence_cutoff: datetime
    confidence: float
    tlp: str


class ThreatFeedStatusResponse(BaseModel):
    provider: str
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    rate_limited_until: datetime | None
    fetched_count: int
    accepted_count: int
    error_count: int
    last_error: str | None


@router.get("/model-scores/{model_score_id}/explanation", response_model=ModelExplanationResponse)
async def get_model_explanation(
    model_score_id: UUID,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ModelExplanationResponse:
    row = await session.scalar(
        select(ModelExplanationModel)
        .join(ModelScoreModel)
        .where(
            ModelScoreModel.model_score_id == model_score_id,
            _scope_access(ModelScoreModel.scope_id, ModelScoreModel.asset_id, principal),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="model explanation not found")
    return ModelExplanationResponse(
        explanation_id=row.explanation_id,
        model_score_id=row.model_score_id,
        method=row.method,
        version=row.version,
        scope_id=row.scope_id,
        status=row.status,
        explanation_hash=row.explanation_hash,
        generated_at=row.generated_at,
        decision_trace=DecisionTrace.model_validate(row.explanation_json),
    )


@router.get("/intelligence/threat/indicators", response_model=list[ThreatIndicatorResponse])
async def list_threat_indicators(
    principal: CurrentPrincipal,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[ThreatIndicatorResponse]:
    latest_observations = (
        select(
            ThreatObservationModel.indicator_id,
            func.max(ThreatObservationModel.fetched_at).label("latest_fetched_at"),
        )
        .group_by(ThreatObservationModel.indicator_id)
        .subquery()
    )
    query = (
        select(ThreatIndicatorModel, ThreatObservationModel)
        .join(
            latest_observations,
            latest_observations.c.indicator_id == ThreatIndicatorModel.indicator_id,
        )
        .join(
            ThreatObservationModel,
            (ThreatObservationModel.indicator_id == ThreatIndicatorModel.indicator_id)
            & (ThreatObservationModel.fetched_at == latest_observations.c.latest_fetched_at),
        )
        .order_by(ThreatIndicatorModel.last_seen.desc())
        .limit(limit)
    )
    if Role.PLATFORM_ADMIN not in principal.roles:
        query = query.join(ThreatMatchModel).where(
            _scope_access(ThreatMatchModel.scope_id, ThreatMatchModel.asset_id, principal)
        )
    rows = (await session.execute(query)).all()
    return [
        ThreatIndicatorResponse(
            indicator_id=indicator.indicator_id,
            indicator_type=indicator.indicator_type,
            normalized_value=indicator.normalized_value,
            active=indicator.active,
            first_seen=indicator.first_seen,
            last_seen=indicator.last_seen,
            tlp=observation.tlp,
            confidence=observation.confidence,
        )
        for indicator, observation in rows
    ]


@router.get("/intelligence/assets/{asset_id}/threat-context", response_model=ThreatContextResponse)
async def get_asset_threat_context(
    asset_id: str,
    principal: CurrentPrincipal,
    scope_id: str = Query(default="LIVE", max_length=128),
    cutoff: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> ThreatContextResponse:
    query = select(ThreatContextSnapshotModel).where(
        ThreatContextSnapshotModel.asset_id == asset_id,
        ThreatContextSnapshotModel.scope_id == scope_id,
        _scope_access(
            ThreatContextSnapshotModel.scope_id,
            ThreatContextSnapshotModel.asset_id,
            principal,
        ),
    )
    if cutoff is not None:
        query = query.where(ThreatContextSnapshotModel.cutoff <= cutoff)
    row = await session.scalar(query.order_by(ThreatContextSnapshotModel.cutoff.desc()).limit(1))
    if row is None:
        raise HTTPException(status_code=404, detail="threat context not found")
    return ThreatContextResponse(
        snapshot_id=row.snapshot_id,
        scope_id=row.scope_id,
        asset_id=row.asset_id,
        cutoff=row.cutoff,
        status=ThreatContextStatus(row.status),
        score=row.score,
        confidence=row.confidence,
        match_ids=row.match_ids_json,
        version=row.version,
    )


@router.get("/intelligence/threat/matches/{match_id}", response_model=ThreatMatchResponse)
async def get_threat_match(
    match_id: UUID,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ThreatMatchResponse:
    result = await session.execute(
        select(ThreatMatchModel, ThreatIndicatorModel, ThreatObservationModel)
        .join(ThreatIndicatorModel)
        .join(
            ThreatObservationModel,
            ThreatObservationModel.observation_id == ThreatMatchModel.observation_id,
        )
        .where(
            ThreatMatchModel.match_id == match_id,
            _scope_access(ThreatMatchModel.scope_id, ThreatMatchModel.asset_id, principal),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="threat match not found")
    match, indicator, observation = row
    return ThreatMatchResponse(
        match_id=match.match_id,
        scope_id=match.scope_id,
        asset_id=match.asset_id,
        post_id=match.post_id,
        indicator_id=match.indicator_id,
        indicator_type=indicator.indicator_type,
        matched_value=match.matched_value,
        match_type=match.match_type,
        event_time=match.event_time,
        evidence_cutoff=match.evidence_cutoff,
        confidence=match.confidence,
        tlp=observation.tlp,
    )


@router.get("/intelligence/threat/feed-status", response_model=ThreatFeedStatusResponse)
async def get_threat_feed_status(
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> ThreatFeedStatusResponse:
    row = await session.get(ThreatFeedStatusModel, "OTX")
    if row is None:
        return ThreatFeedStatusResponse(
            provider="OTX",
            status="NOT_STARTED",
            last_attempt_at=None,
            last_success_at=None,
            rate_limited_until=None,
            fetched_count=0,
            accepted_count=0,
            error_count=0,
            last_error=None,
        )
    return ThreatFeedStatusResponse.model_validate(row, from_attributes=True)


def _scope_access(
    scope_column: InstrumentedAttribute[str],
    asset_column: InstrumentedAttribute[str],
    principal: CurrentPrincipal,
) -> ColumnElement[bool]:
    if Role.PLATFORM_ADMIN in principal.roles:
        return true()
    return or_(
        exists(
            select(CampaignModel.campaign_id).where(
                CampaignModel.tenant_id == principal.tenant_id,
                CampaignModel.scope_id == scope_column,
                CampaignModel.asset_id == asset_column,
            )
        ),
        exists(
            select(ReplaySessionModel.replay_session_id).where(
                ReplaySessionModel.tenant_id == principal.tenant_id,
                ReplaySessionModel.scope_id == scope_column,
            )
        ),
    )
