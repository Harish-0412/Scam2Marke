from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.db.models import (
    AlertActionModel,
    AlertModel,
    AssetModel,
    AuditLogModel,
    CampaignModel,
    GraphFeatureModel,
    GraphSnapshotModel,
    ModelScoreModel,
    NarrativeModel,
    WatchlistAssetModel,
    WatchlistModel,
)
from scam2market.db.session import get_db_session

router = APIRouter()


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scope_id: str = Field(default="LIVE", min_length=1, max_length=128)
    is_default: bool = False


class WatchlistAssetCreate(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)


class AlertActionCreate(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class WatchlistResponse(BaseModel):
    watchlist_id: UUID
    owner_id: str
    scope_id: str
    name: str
    description: str | None
    is_default: bool
    asset_ids: list[str]
    created_at: datetime
    updated_at: datetime


class ScoreResponse(BaseModel):
    model_score_id: UUID
    asset_id: str
    fusion_score: float
    confidence: float
    severity: str
    market_score: float | None
    social_score: float | None
    coordination_score: float | None
    temporal_score: float | None
    graph_score: float | None
    claim_risk: float | None
    evidence_cutoff: datetime
    model_version: str


class CampaignResponse(BaseModel):
    campaign_id: UUID
    scope_id: str
    asset_id: str
    stage: str
    stage_confidence: float
    status: str
    max_severity: str
    first_evidence_at: datetime
    last_evidence_at: datetime
    version: int


class AlertResponse(BaseModel):
    alert_id: UUID
    campaign_id: UUID
    alert_type: str
    severity: str
    status: str
    first_triggered_at: datetime
    last_triggered_at: datetime
    occurrence_count: int
    version: int


class NarrativeResponse(BaseModel):
    narrative_id: UUID
    scope_id: str
    asset_id: str
    label: str
    summary: str
    post_count: int
    unique_author_count: int
    first_seen: datetime
    last_seen: datetime
    revision: int
    embedding_version: str


class AssetOverviewResponse(BaseModel):
    asset: dict[str, str]
    scope_id: str
    latest_score: ScoreResponse | None
    active_campaign: CampaignResponse | None


class TimelineEventResponse(BaseModel):
    event_type: str
    event_time: datetime
    data: dict[str, Any]


class CampaignDetailResponse(CampaignResponse):
    alerts: list[AlertResponse]


class AlertActionResponse(BaseModel):
    action_id: UUID
    action_type: str
    actor_id: str
    note: str | None
    previous_status: str
    resulting_status: str
    created_at: datetime


class AlertDetailResponse(AlertResponse):
    actions: list[AlertActionResponse]


class GraphResponse(BaseModel):
    graph_snapshot_id: UUID
    campaign_id: UUID
    projection_status: str
    node_count: int
    relationship_count: int
    features: dict[str, Any]
    graph_score: float | None


@router.post("/watchlists", status_code=201, response_model=WatchlistResponse)
async def create_watchlist(
    body: WatchlistCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = WatchlistModel(
        owner_id=actor_id,
        scope_id=body.scope_id,
        name=body.name,
        description=body.description,
        is_default=body.is_default,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return await _watchlist_response(session, row)


@router.get("/watchlists", response_model=list[WatchlistResponse])
async def list_watchlists(
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    scope_id: str = "LIVE",
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(WatchlistModel)
            .where(WatchlistModel.owner_id == actor_id, WatchlistModel.scope_id == scope_id)
            .order_by(WatchlistModel.is_default.desc(), WatchlistModel.name)
        )
    ).all()
    return [await _watchlist_response(session, row) for row in rows]


@router.post("/watchlists/{watchlist_id}/assets", status_code=201, response_model=WatchlistResponse)
async def add_watchlist_asset(
    watchlist_id: UUID,
    body: WatchlistAssetCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    watchlist = await _owned_watchlist(session, watchlist_id, actor_id)
    if await session.get(AssetModel, body.asset_id) is None:
        raise HTTPException(status_code=404, detail="asset not found")
    existing = await session.get(WatchlistAssetModel, (watchlist_id, body.asset_id))
    if existing is None:
        session.add(
            WatchlistAssetModel(
                watchlist_id=watchlist_id, asset_id=body.asset_id, added_by=actor_id
            )
        )
        await session.commit()
    return await _watchlist_response(session, watchlist)


@router.delete("/watchlists/{watchlist_id}/assets/{asset_id}", status_code=204)
async def remove_watchlist_asset(
    watchlist_id: UUID,
    asset_id: str,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await _owned_watchlist(session, watchlist_id, actor_id)
    await session.execute(
        delete(WatchlistAssetModel).where(
            WatchlistAssetModel.watchlist_id == watchlist_id,
            WatchlistAssetModel.asset_id == asset_id,
        )
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/assets/{asset_id}/overview", response_model=AssetOverviewResponse)
async def asset_overview(
    asset_id: str,
    scope_id: str = "LIVE",
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    asset = await session.get(AssetModel, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    score = await session.scalar(
        select(ModelScoreModel)
        .where(ModelScoreModel.asset_id == asset_id)
        .order_by(ModelScoreModel.evidence_cutoff.desc())
        .limit(1)
    )
    campaign = await session.scalar(
        select(CampaignModel)
        .where(CampaignModel.asset_id == asset_id, CampaignModel.scope_id == scope_id)
        .order_by(CampaignModel.updated_at.desc())
        .limit(1)
    )
    return {
        "asset": {
            "asset_id": asset.asset_id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
        },
        "scope_id": scope_id,
        "latest_score": _score_response(score) if score else None,
        "active_campaign": _campaign_response(campaign) if campaign else None,
    }


@router.get("/assets/{asset_id}/scores", response_model=list[ScoreResponse])
async def asset_scores(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ModelScoreModel)
            .where(ModelScoreModel.asset_id == asset_id)
            .order_by(ModelScoreModel.evidence_cutoff.desc())
            .limit(limit)
        )
    ).all()
    return [_score_response(row) for row in rows]


@router.get("/assets/{asset_id}/timeline", response_model=list[TimelineEventResponse])
async def asset_timeline(
    asset_id: str,
    scope_id: str = "LIVE",
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    campaigns = (
        await session.scalars(
            select(CampaignModel).where(
                CampaignModel.asset_id == asset_id, CampaignModel.scope_id == scope_id
            )
        )
    ).all()
    campaign_ids = [row.campaign_id for row in campaigns]
    alerts = (
        (
            await session.scalars(
                select(AlertModel).where(AlertModel.campaign_id.in_(campaign_ids))
            )
        ).all()
        if campaign_ids
        else []
    )
    narratives = (
        await session.scalars(
            select(NarrativeModel).where(
                NarrativeModel.asset_id == asset_id, NarrativeModel.scope_id == scope_id
            )
        )
    ).all()
    events: list[dict[str, Any]] = [
        {
            "event_type": "CAMPAIGN",
            "event_time": row.last_evidence_at,
            "data": _campaign_response(row),
        }
        for row in campaigns
    ]
    events.extend(
        {"event_type": "ALERT", "event_time": row.last_triggered_at, "data": _alert_response(row)}
        for row in alerts
    )
    events.extend(
        {"event_type": "NARRATIVE", "event_time": row.last_seen, "data": _narrative_response(row)}
        for row in narratives
    )
    return sorted(events, key=lambda item: item["event_time"], reverse=True)[:limit]


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailResponse)
async def campaign_detail(
    campaign_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    row = await session.get(CampaignModel, campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    alerts = (
        await session.scalars(select(AlertModel).where(AlertModel.campaign_id == campaign_id))
    ).all()
    return {**_campaign_response(row), "alerts": [_alert_response(alert) for alert in alerts]}


@router.get("/alerts/{alert_id}", response_model=AlertDetailResponse)
async def alert_detail(
    alert_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    row = await session.get(AlertModel, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    actions = (
        await session.scalars(
            select(AlertActionModel)
            .where(AlertActionModel.alert_id == alert_id)
            .order_by(AlertActionModel.created_at)
        )
    ).all()
    return {**_alert_response(row), "actions": [_action_response(action) for action in actions]}


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: UUID,
    body: AlertActionCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await session.get(AlertModel, alert_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    previous = row.status
    if previous != "ACKNOWLEDGED":
        row.status = "ACKNOWLEDGED"
        row.version += 1
        action = AlertActionModel(
            alert_id=alert_id,
            action_type="ACKNOWLEDGE",
            actor_id=actor_id,
            note=body.note,
            previous_status=previous,
            resulting_status=row.status,
        )
        session.add(action)
        session.add(
            AuditLogModel(
                actor_id=actor_id,
                action="ACKNOWLEDGE_ALERT",
                target_type="ALERT",
                target_id=str(alert_id),
                reason=body.note,
            )
        )
        await session.commit()
    return _alert_response(row)


@router.get("/assets/{asset_id}/narratives", response_model=list[NarrativeResponse])
async def asset_narratives(
    asset_id: str,
    scope_id: str = "LIVE",
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(NarrativeModel)
            .where(NarrativeModel.asset_id == asset_id, NarrativeModel.scope_id == scope_id)
            .order_by(NarrativeModel.last_seen.desc())
        )
    ).all()
    return [_narrative_response(row) for row in rows]


@router.get("/narratives/{narrative_id}", response_model=NarrativeResponse)
async def narrative_detail(
    narrative_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    row = await session.get(NarrativeModel, narrative_id)
    if row is None:
        raise HTTPException(status_code=404, detail="narrative not found")
    return _narrative_response(row)


@router.get("/campaigns/{campaign_id}/graph", response_model=GraphResponse)
async def campaign_graph(
    campaign_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    campaign = await session.get(CampaignModel, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    row = (
        await session.execute(
            select(GraphSnapshotModel, GraphFeatureModel)
            .join(
                GraphFeatureModel,
                GraphFeatureModel.graph_snapshot_id == GraphSnapshotModel.graph_snapshot_id,
            )
            .where(
                GraphSnapshotModel.scope_id == campaign.scope_id,
                GraphSnapshotModel.asset_id == campaign.asset_id,
            )
            .order_by(GraphSnapshotModel.window_end.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="graph snapshot not found")
    snapshot, features = row
    return {
        "graph_snapshot_id": str(snapshot.graph_snapshot_id),
        "campaign_id": str(campaign_id),
        "projection_status": snapshot.projection_status,
        "node_count": snapshot.node_count,
        "relationship_count": snapshot.relationship_count,
        "features": features.features_json,
        "graph_score": features.graph_score,
    }


async def _owned_watchlist(
    session: AsyncSession, watchlist_id: UUID, actor_id: str
) -> WatchlistModel:
    row = await session.get(WatchlistModel, watchlist_id)
    if row is None or row.owner_id != actor_id:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return row


async def _watchlist_response(session: AsyncSession, row: WatchlistModel) -> dict[str, Any]:
    assets = (
        await session.scalars(
            select(WatchlistAssetModel.asset_id)
            .where(WatchlistAssetModel.watchlist_id == row.watchlist_id)
            .order_by(WatchlistAssetModel.asset_id)
        )
    ).all()
    return {
        "watchlist_id": str(row.watchlist_id),
        "owner_id": row.owner_id,
        "scope_id": row.scope_id,
        "name": row.name,
        "description": row.description,
        "is_default": row.is_default,
        "asset_ids": list(assets),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _campaign_response(row: CampaignModel) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign_id),
        "scope_id": row.scope_id,
        "asset_id": row.asset_id,
        "stage": row.stage,
        "stage_confidence": row.stage_confidence,
        "status": row.status,
        "max_severity": row.max_severity,
        "first_evidence_at": row.first_evidence_at,
        "last_evidence_at": row.last_evidence_at,
        "version": row.version,
    }


def _alert_response(row: AlertModel) -> dict[str, Any]:
    return {
        "alert_id": str(row.alert_id),
        "campaign_id": str(row.campaign_id),
        "alert_type": row.alert_type,
        "severity": row.severity,
        "status": row.status,
        "first_triggered_at": row.first_triggered_at,
        "last_triggered_at": row.last_triggered_at,
        "occurrence_count": row.occurrence_count,
        "version": row.version,
    }


def _narrative_response(row: NarrativeModel) -> dict[str, Any]:
    return {
        "narrative_id": str(row.narrative_id),
        "scope_id": row.scope_id,
        "asset_id": row.asset_id,
        "label": row.label,
        "summary": row.summary,
        "post_count": row.post_count,
        "unique_author_count": row.unique_author_count,
        "first_seen": row.first_seen,
        "last_seen": row.last_seen,
        "revision": row.current_revision,
        "embedding_version": row.embedding_version,
    }


def _score_response(row: ModelScoreModel) -> dict[str, Any]:
    return {
        "model_score_id": str(row.model_score_id),
        "asset_id": row.asset_id,
        "fusion_score": row.fusion_score,
        "confidence": row.confidence,
        "severity": row.severity,
        "market_score": row.market_score,
        "social_score": row.social_score,
        "coordination_score": row.coordination_score,
        "temporal_score": row.temporal_score,
        "graph_score": row.graph_score,
        "claim_risk": row.claim_risk,
        "evidence_cutoff": row.evidence_cutoff,
        "model_version": row.model_version,
    }


def _action_response(row: AlertActionModel) -> dict[str, Any]:
    return {
        "action_id": str(row.action_id),
        "action_type": row.action_type,
        "actor_id": row.actor_id,
        "note": row.note,
        "previous_status": row.previous_status,
        "resulting_status": row.resulting_status,
        "created_at": row.created_at,
    }
