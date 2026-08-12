from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.db.models import (
    NotificationChannelModel,
    NotificationDeliveryModel,
    NotificationSubscriptionModel,
)
from scam2market.db.session import get_db_session
from scam2market.security.auth import CurrentPrincipal, Principal, require_permission

router = APIRouter(prefix="/notifications")


class ChannelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    channel_type: Literal["SLACK", "TEAMS", "EMAIL", "WEBHOOK"]
    endpoint: str = Field(min_length=3, max_length=2000)
    secret: str | None = Field(default=None, min_length=16)
    config: dict[str, Any] = Field(default_factory=dict)


class SubscriptionCreate(BaseModel):
    channel_id: UUID
    minimum_severity: Literal["INFO", "WATCH", "HIGH", "CRITICAL"] = "HIGH"
    asset_ids: list[str] = Field(default_factory=list)
    alert_types: list[str] = Field(default_factory=list)


@router.post("/channels", status_code=201)
async def create_channel(
    body: ChannelCreate,
    principal: CurrentPrincipal,
    _: Principal = Depends(require_permission("notification:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if body.channel_type != "EMAIL":
        HttpUrl(body.endpoint)
    row = NotificationChannelModel(
        tenant_id=principal.tenant_id,
        name=body.name,
        channel_type=body.channel_type,
        endpoint=body.endpoint,
        secret=body.secret,
        config_json=body.config,
        created_by=principal.subject,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _channel_response(row)


@router.get("/channels")
async def list_channels(
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(NotificationChannelModel)
            .where(NotificationChannelModel.tenant_id == principal.tenant_id)
            .order_by(NotificationChannelModel.name)
        )
    ).all()
    return [_channel_response(row) for row in rows]


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    body: SubscriptionCreate,
    principal: CurrentPrincipal,
    _: Principal = Depends(require_permission("notification:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    channel = await session.scalar(
        select(NotificationChannelModel).where(
            NotificationChannelModel.channel_id == body.channel_id,
            NotificationChannelModel.tenant_id == principal.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="notification channel not found")
    row = NotificationSubscriptionModel(
        tenant_id=principal.tenant_id,
        channel_id=body.channel_id,
        minimum_severity=body.minimum_severity,
        asset_ids_json=sorted(set(body.asset_ids)),
        alert_types_json=sorted(set(body.alert_types)),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "subscription_id": row.subscription_id,
        "channel_id": row.channel_id,
        "minimum_severity": row.minimum_severity,
        "asset_ids": row.asset_ids_json,
        "alert_types": row.alert_types_json,
        "enabled": row.enabled,
    }


@router.get("/deliveries")
async def list_deliveries(
    principal: CurrentPrincipal,
    delivery_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(NotificationDeliveryModel).where(
        NotificationDeliveryModel.tenant_id == principal.tenant_id
    )
    if delivery_status:
        query = query.where(NotificationDeliveryModel.status == delivery_status.upper())
    rows = (
        await session.scalars(
            query.order_by(NotificationDeliveryModel.created_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "delivery_id": row.delivery_id,
            "channel_id": row.channel_id,
            "event_id": row.event_id,
            "alert_id": row.alert_id,
            "status": row.status,
            "attempts": row.attempts,
            "next_attempt_at": row.next_attempt_at,
            "delivered_at": row.delivered_at,
            "response_code": row.response_code,
            "last_error": row.last_error,
        }
        for row in rows
    ]


def _channel_response(row: NotificationChannelModel) -> dict[str, Any]:
    return {
        "channel_id": row.channel_id,
        "name": row.name,
        "channel_type": row.channel_type,
        "endpoint": row.endpoint,
        "enabled": row.enabled,
        "has_secret": bool(row.secret),
        "config": {key: value for key, value in row.config_json.items() if key != "password"},
    }
