from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    AssetBaselineModel,
    AssetLiquidityClassModel,
    EventIngestionLogModel,
    EventOutboxModel,
    FeatureLineageModel,
    FeatureRevisionModel,
    FeatureWindowModel,
    MarketCandleModel,
    MarketRegimeModel,
    MarketTradeModel,
    ModelScoreModel,
    OrderBookFeatureModel,
    OrderBookSnapshotModel,
    PostAssetMentionModel,
    SocialPostModel,
)
from scam2market.features.schemas import FeatureSnapshot
from scam2market.ingestion.market import MarketDatum
from scam2market.intelligence.fusion import FusionResult
from scam2market.schemas.domain import (
    AssetMention,
    MarketCandle,
    MarketTrade,
    OrderBookUpdate,
    SocialPost,
)
from scam2market.schemas.events import CanonicalEvent
from scam2market.streaming.outbox import OutboxMessage


def _is_unique_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == "23505"


def _ingestion_log(event: CanonicalEvent) -> EventIngestionLogModel:
    return EventIngestionLogModel(
        event_id=event.event_id,
        dedupe_key=event.dedupe_key(),
        event_type=event.event_type.value,
        schema_version=event.schema_version,
        source=event.source,
        source_event_id=event.source_event_id,
        source_sequence=event.source_sequence,
        asset_id=event.asset_id,
        event_time=event.event_time,
        ingested_at=event.ingested_at,
        processed_at=event.processed_at,
        partition_key=event.partition_key,
        is_replay=event.replay.is_replay,
        replay_session_id=event.replay.replay_session_id,
        correlation_id=event.trace.correlation_id,
        causation_id=event.trace.causation_id,
        payload_json=event.payload,
    )


def _outbox(event: CanonicalEvent, topic: str) -> EventOutboxModel:
    return EventOutboxModel(
        event_id=event.event_id,
        topic=topic,
        partition_key=event.partition_key,
        envelope_json=event.model_dump(mode="json"),
        status="PENDING",
        attempts=0,
    )


class SqlMarketRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist(self, event: CanonicalEvent, datum: MarketDatum, topic: str) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(_ingestion_log(event))
                    session.add(_outbox(event, topic))
                    session.add(self._market_row(event, datum))
                    if isinstance(datum, OrderBookUpdate):
                        session.add(self._orderbook_feature(event, datum))
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True

    async def mark_published(self, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(EventOutboxModel)
                .where(EventOutboxModel.event_id == event_id)
                .values(status="PUBLISHED", published_at=datetime.now().astimezone())
            )

    @staticmethod
    def _market_row(
        event: CanonicalEvent, datum: MarketDatum
    ) -> MarketTradeModel | MarketCandleModel | OrderBookSnapshotModel:
        replay_session_id = event.replay.replay_session_id
        scope_id = replay_session_id or "LIVE"
        if isinstance(datum, MarketTrade):
            return MarketTradeModel(
                scope_id=scope_id,
                event_time=datum.event_time,
                source=event.source,
                trade_id=datum.trade_id,
                asset_id=datum.asset_id,
                source_sequence=event.source_sequence,
                price=datum.price,
                quantity=datum.quantity,
                side=datum.side,
                ingested_at=event.ingested_at,
                replay_session_id=replay_session_id,
            )
        if isinstance(datum, MarketCandle):
            return MarketCandleModel(
                scope_id=scope_id,
                event_time=datum.event_time,
                source=event.source,
                candle_id=datum.candle_id,
                asset_id=datum.asset_id,
                source_sequence=event.source_sequence,
                interval_seconds=datum.interval_seconds,
                open=datum.open,
                high=datum.high,
                low=datum.low,
                close=datum.close,
                volume=datum.volume,
                ingested_at=event.ingested_at,
                replay_session_id=replay_session_id,
            )
        return OrderBookSnapshotModel(
            scope_id=scope_id,
            event_time=datum.event_time,
            source=event.source,
            update_id=datum.update_id,
            asset_id=datum.asset_id,
            source_sequence=event.source_sequence,
            best_bid=datum.best_bid,
            best_ask=datum.best_ask,
            bids_json=[[price, quantity] for price, quantity in datum.bids],
            asks_json=[[price, quantity] for price, quantity in datum.asks],
            ingested_at=event.ingested_at,
            replay_session_id=replay_session_id,
        )

    @staticmethod
    def _orderbook_feature(event: CanonicalEvent, datum: OrderBookUpdate) -> OrderBookFeatureModel:
        bid_depth = datum.top_bid_depth or 0.0
        ask_depth = datum.top_ask_depth or 0.0
        total_depth = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total_depth if total_depth else None
        return OrderBookFeatureModel(
            scope_id=event.replay.replay_session_id or "LIVE",
            event_time=datum.event_time,
            source=event.source,
            snapshot_id=datum.update_id,
            asset_id=datum.asset_id,
            spread=datum.spread,
            top_n_depth=total_depth or None,
            imbalance=imbalance,
        )


class InMemoryMarketRepository:
    def __init__(self) -> None:
        self.events: dict[str, MarketDatum] = {}
        self.published: set[str] = set()

    async def persist(self, event: CanonicalEvent, datum: MarketDatum, topic: str) -> bool:
        del topic
        key = event.dedupe_key()
        if key in self.events:
            return False
        self.events[key] = datum
        return True

    async def mark_published(self, event_id: str) -> None:
        self.published.add(event_id)


class SqlSocialRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist(
        self,
        raw_event: CanonicalEvent,
        post: SocialPost,
        mentions: Sequence[AssetMention],
        published_events: Sequence[tuple[str, CanonicalEvent]],
    ) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    for topic, published_event in published_events:
                        session.add(_ingestion_log(published_event))
                        session.add(_outbox(published_event, topic))
                    post_row = SocialPostModel(
                        post_id=post.post_id,
                        scope_id=raw_event.replay.replay_session_id or "LIVE",
                        source=raw_event.source,
                        source_post_id=raw_event.source_event_id,
                        platform=post.platform,
                        pseudonymous_author_id=post.author_id,
                        event_time=post.event_time,
                        ingested_at=raw_event.ingested_at,
                        text=post.text,
                        language=post.language,
                        hashtags_json=post.hashtags,
                        cashtags_json=post.cashtags,
                        urls_json=post.urls,
                        user_mentions_json=post.user_mentions,
                        reply_to=post.reply_to,
                        repost_of=post.repost_of,
                        engagement_json=post.engagement,
                        replay_session_id=raw_event.replay.replay_session_id,
                    )
                    session.add(post_row)
                    await session.flush()
                    session.add_all(
                        [
                            PostAssetMentionModel(
                                post_id=mention.post_id,
                                asset_id=mention.asset_id,
                                mention_text=mention.mention_text,
                                start_offset=mention.start_offset,
                                end_offset=mention.end_offset,
                                confidence=mention.confidence,
                                resolver_version=mention.resolver_version,
                                resolution_status=mention.resolution_status,
                                candidate_asset_ids_json=mention.candidate_asset_ids,
                            )
                            for mention in mentions
                        ]
                    )
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True

    async def mark_published(self, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(EventOutboxModel)
                .where(EventOutboxModel.event_id == event_id)
                .values(status="PUBLISHED", published_at=datetime.now().astimezone())
            )


class InMemorySocialRepository:
    def __init__(self) -> None:
        self.posts: dict[str, SocialPost] = {}
        self.mentions: list[AssetMention] = []
        self.published: set[str] = set()

    async def persist(
        self,
        raw_event: CanonicalEvent,
        post: SocialPost,
        mentions: Sequence[AssetMention],
        published_events: Sequence[tuple[str, CanonicalEvent]],
    ) -> bool:
        del published_events
        key = raw_event.dedupe_key()
        if key in self.posts:
            return False
        self.posts[key] = post
        self.mentions.extend(mentions)
        return True

    async def mark_published(self, event_id: str) -> None:
        self.published.add(event_id)


def serialize_latest_post(post: SocialPost, mentions: Sequence[AssetMention]) -> dict[str, Any]:
    return {
        "post": post.model_dump(mode="json"),
        "mentions": [mention.model_dump(mode="json") for mention in mentions],
    }


class SqlFeatureRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist(self, snapshot: FeatureSnapshot) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    window = await session.scalar(
                        select(FeatureWindowModel).where(
                            FeatureWindowModel.scope_id == snapshot.scope_id,
                            FeatureWindowModel.asset_id == snapshot.asset_id,
                            FeatureWindowModel.window_start == snapshot.window_start,
                            FeatureWindowModel.interval_seconds == snapshot.interval_seconds,
                        )
                    )
                    if window is None:
                        window = FeatureWindowModel(
                            feature_window_id=snapshot.feature_window_id,
                            scope_id=snapshot.scope_id,
                            asset_id=snapshot.asset_id,
                            window_start=snapshot.window_start,
                            window_end=snapshot.window_end,
                            interval_seconds=snapshot.interval_seconds,
                            current_revision=snapshot.revision,
                            is_final=snapshot.is_final,
                            feature_schema_version=snapshot.feature_schema_version,
                        )
                        session.add(window)
                    elif window.current_revision >= snapshot.revision:
                        return False
                    else:
                        window.current_revision = snapshot.revision
                        window.is_final = snapshot.is_final
                        window.feature_schema_version = snapshot.feature_schema_version
                    await session.flush()
                    session.add(
                        FeatureLineageModel(
                            lineage_id=snapshot.lineage.lineage_id,
                            source_event_ids_json=snapshot.lineage.source_event_ids,
                            source_event_min_time=snapshot.lineage.source_event_min_time,
                            source_event_max_time=snapshot.lineage.source_event_max_time,
                            source_count=snapshot.lineage.source_count,
                            source_hash=snapshot.lineage.source_hash,
                        )
                    )
                    await session.flush()
                    session.add(
                        FeatureRevisionModel(
                            feature_window_id=snapshot.feature_window_id,
                            revision=snapshot.revision,
                            lineage_id=snapshot.lineage.lineage_id,
                            is_final=snapshot.is_final,
                            features_json=snapshot.features,
                        )
                    )
                    baseline = await session.get(
                        AssetBaselineModel,
                        {
                            "scope_id": snapshot.scope_id,
                            "asset_id": snapshot.asset_id,
                            "feature_schema_version": snapshot.feature_schema_version,
                        },
                    )
                    confidence = float(snapshot.features["baseline_confidence"] or 0.0)
                    metrics = {
                        "volume": snapshot.features["volume"],
                        "volatility": snapshot.features["volatility"],
                        "relative_volume": snapshot.features["relative_volume"],
                        "window_end": snapshot.window_end.isoformat(),
                    }
                    if baseline is None:
                        session.add(
                            AssetBaselineModel(
                                scope_id=snapshot.scope_id,
                                asset_id=snapshot.asset_id,
                                feature_schema_version=snapshot.feature_schema_version,
                                history_window_count=round(confidence * 20),
                                confidence=confidence,
                                baseline_json=metrics,
                            )
                        )
                    else:
                        baseline.history_window_count = round(confidence * 20)
                        baseline.confidence = confidence
                        baseline.baseline_json = metrics
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True


class SqlScoreRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist(self, result: FusionResult) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(
                        ModelScoreModel(
                            asset_id=result.asset_id,
                            feature_window_id=UUID(result.feature_window_id),
                            feature_revision=result.feature_revision,
                            model_version=result.model_version,
                            market_score=result.market_score,
                            social_score=result.social_score,
                            coordination_score=result.coordination_score,
                            temporal_score=result.temporal_score,
                            claim_risk=result.claim_risk,
                            legitimate_event_score=result.legitimate_event_score,
                            fusion_score=result.fusion_score,
                            confidence=result.confidence,
                            severity=result.severity.value,
                            missing_outputs_json=result.missing_outputs,
                            scored_at=result.scored_at,
                        )
                    )
                    session.add(
                        MarketRegimeModel(
                            asset_id=result.asset_id,
                            event_time=result.scored_at,
                            regime=result.market_regime,
                            confidence=result.confidence,
                            inputs_json={
                                "feature_window_id": result.feature_window_id,
                                "feature_revision": result.feature_revision,
                            },
                        )
                    )
                    liquidity = await session.get(AssetLiquidityClassModel, result.asset_id)
                    if liquidity is None:
                        session.add(
                            AssetLiquidityClassModel(
                                asset_id=result.asset_id,
                                liquidity_class=result.liquidity_class,
                                confidence=result.confidence,
                                metrics_json={
                                    "feature_window_id": result.feature_window_id,
                                    "feature_revision": result.feature_revision,
                                },
                            )
                        )
                    else:
                        liquidity.liquidity_class = result.liquidity_class
                        liquidity.confidence = result.confidence
                        liquidity.metrics_json = {
                            "feature_window_id": result.feature_window_id,
                            "feature_revision": result.feature_revision,
                        }
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True


class SqlOutboxRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def pending(self, limit: int = 100) -> list[OutboxMessage]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EventOutboxModel)
                    .where(
                        EventOutboxModel.status.in_(("PENDING", "FAILED")),
                        EventOutboxModel.attempts < 10,
                    )
                    .order_by(EventOutboxModel.created_at)
                    .limit(limit)
                )
            ).all()
        return [
            OutboxMessage(
                outbox_id=row.outbox_id,
                topic=row.topic,
                event=CanonicalEvent.model_validate(row.envelope_json),
            )
            for row in rows
        ]

    async def mark_published(self, outbox_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(EventOutboxModel)
                .where(EventOutboxModel.outbox_id == outbox_id)
                .values(status="PUBLISHED", published_at=datetime.now().astimezone())
            )

    async def mark_failed(self, outbox_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(EventOutboxModel)
                .where(EventOutboxModel.outbox_id == outbox_id)
                .values(status="FAILED", attempts=EventOutboxModel.attempts + 1)
            )
