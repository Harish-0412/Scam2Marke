from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
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
    WorkerCheckpointModel,
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
        origin_event_id=str(event.origin_event_id),
        delivery_event_id=str(event.delivery_event_id),
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


class SqlMarketRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist(self, event: CanonicalEvent, datum: MarketDatum) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(_ingestion_log(event))
                    session.add(self._market_row(event, datum))
                    if isinstance(datum, OrderBookUpdate):
                        session.add(self._orderbook_feature(event, datum))
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True

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
        quality = event.payload.get("_quality", {})
        book_valid = bool(quality.get("book_valid", True))
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
            orderbook_state=str(quality.get("orderbook_state", "VALID")),
            book_valid=book_valid,
            ingested_at=event.ingested_at,
            replay_session_id=replay_session_id,
        )

    @staticmethod
    def _orderbook_feature(event: CanonicalEvent, datum: OrderBookUpdate) -> OrderBookFeatureModel:
        quality = event.payload.get("_quality", {})
        book_valid = bool(quality.get("book_valid", True))
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
            spread=datum.spread if book_valid else None,
            top_n_depth=(total_depth or None) if book_valid else None,
            imbalance=imbalance if book_valid else None,
            book_valid=book_valid,
        )


class InMemoryMarketRepository:
    def __init__(self) -> None:
        self.events: dict[str, MarketDatum] = {}
        self.published: set[str] = set()

    async def persist(self, event: CanonicalEvent, datum: MarketDatum) -> bool:
        key = event.dedupe_key()
        if key in self.events:
            return False
        self.events[key] = datum
        return True


class SqlSocialRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist_raw(self, event: CanonicalEvent) -> bool:
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(_ingestion_log(event))
            except IntegrityError as error:
                await session.rollback()
                if _is_unique_violation(error):
                    return False
                raise
        return True

    async def persist_pair(
        self, normalized_event: CanonicalEvent, mention_event: CanonicalEvent
    ) -> bool:
        post = SocialPost.model_validate(normalized_event.payload)
        raw_mentions = mention_event.payload.get("mentions", [])
        if not isinstance(raw_mentions, list):
            raise TypeError("social mention event payload must contain a list")
        mentions = [AssetMention.model_validate(item) for item in raw_mentions]
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(_ingestion_log(normalized_event))
                    session.add(_ingestion_log(mention_event))
                    post_row = SocialPostModel(
                        post_id=post.post_id,
                        scope_id=normalized_event.replay.replay_session_id or "LIVE",
                        source=normalized_event.source,
                        source_post_id=str(
                            post.source_metadata.get(
                                "source_post_id", normalized_event.source_event_id
                            )
                        ),
                        platform=post.platform,
                        pseudonymous_author_id=post.author_id,
                        pseudonym_key_version=post.pseudonym_key_version,
                        event_time=post.event_time,
                        ingested_at=normalized_event.ingested_at,
                        text=post.text,
                        language=post.language,
                        hashtags_json=post.hashtags,
                        cashtags_json=post.cashtags,
                        urls_json=post.urls,
                        user_mentions_json=post.user_mentions,
                        reply_to=post.reply_to,
                        repost_of=post.repost_of,
                        engagement_json=post.engagement,
                        replay_session_id=normalized_event.replay.replay_session_id,
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
                                resolution_reason=mention.resolution_reason,
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


class InMemorySocialRepository:
    def __init__(self) -> None:
        self.posts: dict[str, SocialPost] = {}
        self.mentions: list[AssetMention] = []
        self.published: set[str] = set()

    async def persist_raw(self, event: CanonicalEvent) -> bool:
        key = event.dedupe_key()
        if key in self.posts:
            return False
        self.posts[key] = SocialPost.model_construct(
            post_id=event.event_id,
            platform="raw",
            author_id="raw",
            event_time=event.event_time,
            text="",
        )
        return True

    async def persist_pair(
        self, normalized_event: CanonicalEvent, mention_event: CanonicalEvent
    ) -> bool:
        post = SocialPost.model_validate(normalized_event.payload)
        key = normalized_event.dedupe_key()
        if key in self.posts:
            return False
        raw_mentions = mention_event.payload.get("mentions", [])
        if not isinstance(raw_mentions, list):
            raise TypeError("social mention event payload must contain a list")
        self.posts[key] = post
        mentions = [AssetMention.model_validate(item) for item in raw_mentions]
        self.mentions.extend(mentions)
        return True


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
                            revision_state=snapshot.revision_state.value,
                            feature_schema_version=snapshot.feature_schema_version,
                            feature_schema_hash=snapshot.feature_schema_hash,
                        )
                        session.add(window)
                    elif window.current_revision >= snapshot.revision:
                        return False
                    else:
                        window.current_revision = snapshot.revision
                        window.is_final = snapshot.is_final
                        window.revision_state = snapshot.revision_state.value
                        window.feature_schema_version = snapshot.feature_schema_version
                        window.feature_schema_hash = snapshot.feature_schema_hash
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
                            revision_state=snapshot.revision_state.value,
                            supersedes_revision=snapshot.supersedes_revision,
                            feature_schema_hash=snapshot.feature_schema_hash,
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
        if result.evidence_cutoff is None:
            raise ValueError("fusion evidence cutoff is required for persistence")
        async with self._sessions() as session:
            try:
                async with session.begin():
                    session.add(
                        ModelScoreModel(
                            asset_id=result.asset_id,
                            feature_window_id=UUID(result.feature_window_id),
                            feature_revision=result.feature_revision,
                            model_version=result.model_version,
                            base_model_version=result.base_model_version,
                            fusion_policy_version=result.fusion_policy_version,
                            enrichment_profile=result.enrichment_profile.value,
                            fusion_revision=result.fusion_revision,
                            evidence_cutoff=result.evidence_cutoff,
                            input_snapshot_ids_json=result.input_snapshot_ids,
                            idempotency_key=result.idempotency_key,
                            market_score=result.market_score,
                            social_score=result.social_score,
                            coordination_score=result.coordination_score,
                            temporal_score=result.temporal_score,
                            claim_risk=result.claim_risk,
                            legitimate_event_score=result.legitimate_event_score,
                            graph_score=result.graph_score,
                            market_anomaly_risk=result.market_anomaly_risk,
                            market_anomaly_severity=result.market_anomaly_severity.value,
                            social_coordination_risk=result.social_coordination_risk,
                            social_coordination_severity=(
                                result.social_coordination_severity.value
                            ),
                            raw_cross_domain_risk=result.raw_cross_domain_risk,
                            context_adjusted_risk=result.context_adjusted_risk,
                            fusion_score=result.fusion_score,
                            confidence=result.confidence,
                            severity=result.severity.value,
                            missing_outputs_json=[
                                item.model_dump(mode="json") for item in result.missing_outputs
                            ],
                            market_regime_confidence=result.market_regime_confidence,
                            liquidity_confidence=result.liquidity_confidence,
                            stage_signals_json=result.stage_signals,
                            scored_at=result.scored_at,
                        )
                    )
                    session.add(
                        MarketRegimeModel(
                            asset_id=result.asset_id,
                            event_time=result.scored_at,
                            regime=result.market_regime,
                            confidence=result.market_regime_confidence,
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
                                confidence=result.liquidity_confidence,
                                metrics_json={
                                    "feature_window_id": result.feature_window_id,
                                    "feature_revision": result.feature_revision,
                                },
                            )
                        )
                    else:
                        liquidity.liquidity_class = result.liquidity_class
                        liquidity.confidence = result.liquidity_confidence
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
        now = datetime.now(tz=UTC)
        stale_claim = now - timedelta(minutes=5)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(EventOutboxModel)
                    .where(
                        (
                            EventOutboxModel.status.in_(("PENDING", "FAILED"))
                            | (
                                (EventOutboxModel.status == "PROCESSING")
                                & (EventOutboxModel.claimed_at < stale_claim)
                            )
                        ),
                        EventOutboxModel.attempts < 10,
                    )
                    .order_by(EventOutboxModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.status = "PROCESSING"
                row.claimed_at = now
                row.attempts += 1
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
                .values(
                    status="PUBLISHED",
                    published_at=datetime.now(tz=UTC),
                    last_error=None,
                )
            )

    async def mark_failed(self, outbox_id: UUID, error: str | None = None) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(EventOutboxModel)
                .where(EventOutboxModel.outbox_id == outbox_id)
                .values(status="FAILED", last_error=(error or "publish failed")[:2000])
            )


class SqlWorkerCheckpointRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(
        self,
        *,
        consumer_group: str,
        topic: str,
        partition: int,
        last_durable_offset: int,
        feature_state_version: str | None = None,
        state_json: dict[str, Any] | None = None,
        state_checksum: str | None = None,
        event_time: datetime | None = None,
    ) -> None:
        async with self._sessions.begin() as session:
            checkpoint = await session.get(
                WorkerCheckpointModel,
                {
                    "consumer_group": consumer_group,
                    "topic": topic,
                    "partition": partition,
                },
            )
            if checkpoint is None:
                session.add(
                    WorkerCheckpointModel(
                        consumer_group=consumer_group,
                        topic=topic,
                        partition=partition,
                        last_durable_offset=last_durable_offset,
                        feature_state_version=feature_state_version,
                        state_json=state_json,
                        state_checksum=state_checksum,
                        event_time=event_time,
                    )
                )
                return
            checkpoint.last_durable_offset = max(
                checkpoint.last_durable_offset, last_durable_offset
            )
            checkpoint.feature_state_version = feature_state_version
            checkpoint.state_json = state_json
            checkpoint.state_checksum = state_checksum
            checkpoint.event_time = event_time

    async def latest(self, consumer_group: str) -> WorkerCheckpointModel | None:
        async with self._sessions() as session:
            checkpoint: WorkerCheckpointModel | None = await session.scalar(
                select(WorkerCheckpointModel)
                .where(WorkerCheckpointModel.consumer_group == consumer_group)
                .order_by(WorkerCheckpointModel.updated_at.desc())
                .limit(1)
            )
            return checkpoint
