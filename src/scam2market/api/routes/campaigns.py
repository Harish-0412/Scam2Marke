from collections.abc import AsyncIterator
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import (
    AlertModel,
    CampaignModel,
    GraphFeatureModel,
    GraphSnapshotModel,
    NarrativeModel,
)
from scam2market.db.session import get_db_session
from scam2market.realtime import RealtimeBroker, RedisRealtimeBroker
from scam2market.security.auth import CurrentPrincipal

router = APIRouter()


async def get_realtime_broker() -> AsyncIterator[RealtimeBroker]:
    settings = get_settings()
    broker = RedisRealtimeBroker(
        settings.redis_url,
        settings.realtime_stream_key,
        settings.realtime_stream_max_length,
    )
    try:
        yield broker
    finally:
        await broker.close()


@router.get("/campaigns")
async def campaigns(
    principal: CurrentPrincipal,
    asset_id: str | None = None,
    scope_id: str = "LIVE",
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(CampaignModel).where(
        CampaignModel.tenant_id == principal.tenant_id,
        CampaignModel.scope_id == scope_id,
    )
    if asset_id is not None:
        query = query.where(CampaignModel.asset_id == asset_id)
    rows = (
        await session.scalars(query.order_by(CampaignModel.updated_at.desc()).limit(limit))
    ).all()
    return [
        {
            "campaign_id": str(row.campaign_id),
            "scope_id": row.scope_id,
            "asset_id": row.asset_id,
            "stage": row.stage,
            "stage_confidence": row.stage_confidence,
            "stage_reason": row.stage_reason_json,
            "stage_rule_version": row.stage_rule_version,
            "status": row.status,
            "max_severity": row.max_severity,
            "first_evidence_at": row.first_evidence_at,
            "last_evidence_at": row.last_evidence_at,
            "version": row.version,
            "last_applied_evidence_cutoff": row.last_applied_evidence_cutoff,
            "last_applied_feature_revision": row.last_applied_feature_revision,
            "last_applied_fusion_revision": row.last_applied_fusion_revision,
            "last_applied_enrichment_profile": row.last_applied_enrichment_profile,
        }
        for row in rows
    ]


@router.get("/alerts")
async def alerts(
    principal: CurrentPrincipal,
    campaign_id: str | None = None,
    scope_id: str = "LIVE",
    status: str = "ACTIVE",
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = (
        select(AlertModel)
        .join(CampaignModel, CampaignModel.campaign_id == AlertModel.campaign_id)
        .where(
            AlertModel.tenant_id == principal.tenant_id,
            AlertModel.status == status,
            CampaignModel.scope_id == scope_id,
        )
    )
    if campaign_id is not None:
        query = query.where(AlertModel.campaign_id == campaign_id)
    rows = (
        await session.scalars(query.order_by(AlertModel.last_triggered_at.desc()).limit(limit))
    ).all()
    return [
        {
            "alert_id": str(row.alert_id),
            "campaign_id": str(row.campaign_id),
            "alert_type": row.alert_type,
            "severity": row.severity,
            "status": row.status,
            "last_triggered_at": row.last_triggered_at,
            "occurrence_count": row.occurrence_count,
            "version": row.version,
        }
        for row in rows
    ]


@router.get("/campaigns/{campaign_id}/evidence")
async def campaign_evidence(
    campaign_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    campaign = await session.get(CampaignModel, campaign_id)
    if campaign is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="campaign not found")
    narrative = (
        await session.get(NarrativeModel, campaign.dominant_narrative_id)
        if campaign.dominant_narrative_id
        else None
    )
    graph_row = (
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
    return {
        "campaign_id": str(campaign.campaign_id),
        "asset_id": campaign.asset_id,
        "stage": campaign.stage,
        "stage_confidence": campaign.stage_confidence,
        "stage_reason": campaign.stage_reason_json,
        "dominant_narrative": (
            {
                "narrative_id": str(narrative.narrative_id),
                "label": narrative.label,
                "summary": narrative.summary,
                "post_count": narrative.post_count,
            }
            if narrative
            else None
        ),
        "graph": (
            {
                "graph_snapshot_id": str(graph_row[0].graph_snapshot_id),
                "projection_status": graph_row[0].projection_status,
                "node_count": graph_row[0].node_count,
                "relationship_count": graph_row[0].relationship_count,
                "features": graph_row[1].features_json,
                "graph_score": graph_row[1].graph_score,
            }
            if graph_row
            else None
        ),
    }


@router.get("/stream/alerts", response_class=StreamingResponse)
async def alert_sse(
    broker: Annotated[RealtimeBroker, Depends(get_realtime_broker)],
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    async def events() -> AsyncIterator[bytes]:
        async for event_id, payload in broker.subscribe(last_event_id or "$"):
            if not event_id:
                yield b": heartbeat\n\n"
                continue
            yield b"id: " + event_id.encode() + b"\n"
            event_name = str(payload.get("event_type", "alert"))
            yield b"event: " + event_name.encode() + b"\n"
            yield b"data: " + orjson.dumps(payload) + b"\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/alerts")
async def alert_websocket(
    websocket: WebSocket,
    broker: Annotated[RealtimeBroker, Depends(get_realtime_broker)],
    after_id: str = "$",
) -> None:
    await websocket.accept()
    try:
        async for event_id, payload in broker.subscribe(after_id):
            if event_id:
                await websocket.send_json({"stream_id": event_id, "event": payload})
    except WebSocketDisconnect:
        return
