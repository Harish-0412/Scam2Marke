from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import PostAssetMentionModel, SocialPostModel
from scam2market.db.session import get_db_session
from scam2market.state import RedisStateStore

router = APIRouter()


async def _read_state(key: str) -> dict[str, Any]:
    store = RedisStateStore(get_settings().redis_url)
    try:
        value = await store.get_json(key)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="online state is unavailable") from exc
    finally:
        await store.close()
    if value is None:
        raise HTTPException(status_code=404, detail="state has not been observed")
    return value


@router.get("/market/assets/{asset_id}/latest")
async def latest_market_state(asset_id: str) -> dict[str, Any]:
    return await _read_state(f"latest:market:{asset_id}")


@router.get("/market/sources/{source}/{asset_id}/health")
async def market_source_health(source: str, asset_id: str) -> dict[str, Any]:
    return await _read_state(f"source-health:market:{source}:{asset_id}")


@router.get("/social/platforms/{platform}/latest")
async def latest_social_state(platform: str) -> dict[str, Any]:
    return await _read_state(f"latest:social:{platform}")


@router.get("/social/assets/{asset_id}/mentions")
async def asset_mentions(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                PostAssetMentionModel.post_id,
                PostAssetMentionModel.mention_text,
                PostAssetMentionModel.confidence,
                PostAssetMentionModel.resolver_version,
                PostAssetMentionModel.resolution_status,
                PostAssetMentionModel.resolution_reason,
                PostAssetMentionModel.candidate_asset_ids_json,
                SocialPostModel.event_time,
            )
            .join(SocialPostModel, SocialPostModel.post_id == PostAssetMentionModel.post_id)
            .where(PostAssetMentionModel.asset_id == asset_id)
            .order_by(SocialPostModel.event_time.desc())
            .limit(limit)
        )
    ).mappings()
    return [dict(row) for row in rows]


@router.get("/social/sources/{source}/{platform}/health")
async def social_source_health(source: str, platform: str) -> dict[str, Any]:
    return await _read_state(f"source-health:social:{source}:{platform}")


@router.get("/features/assets/{asset_id}/latest")
async def latest_features(
    asset_id: str,
    interval_seconds: int = Query(default=60, gt=0),
    scope_id: str | None = None,
) -> dict[str, Any]:
    if interval_seconds not in get_settings().feature_window_intervals_seconds:
        raise HTTPException(status_code=422, detail="unsupported feature window interval")
    if scope_id is not None:
        return await _read_state(f"latest:features:{scope_id}:{asset_id}:{interval_seconds}")
    return await _read_state(f"latest:features:{asset_id}:{interval_seconds}")


@router.get("/intelligence/assets/{asset_id}/score")
async def latest_score(asset_id: str, scope_id: str | None = None) -> dict[str, Any]:
    if scope_id is not None:
        return await _read_state(f"latest:score:{scope_id}:{asset_id}")
    return await _read_state(f"latest:score:{asset_id}")
