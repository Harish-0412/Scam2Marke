from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scam2market.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AssetModel(TimestampMixin, Base):
    __tablename__ = "assets"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64))
    quote_asset: Mapped[str | None] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DataSourceModel(TimestampMixin, Base):
    __tablename__ = "data_sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ReplaySessionModel(TimestampMixin, Base):
    __tablename__ = "replay_sessions"

    replay_session_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    speed_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventIngestionLogModel(Base):
    __tablename__ = "event_ingestion_log"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_event_ingestion_dedupe_key"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sequence: Mapped[int | None] = mapped_column(Integer)
    asset_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    is_replay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replay_session_id: Mapped[str | None] = mapped_column(String(128), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class SchemaVersionModel(TimestampMixin, Base):
    __tablename__ = "schema_versions"

    schema_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compatibility: Mapped[str] = mapped_column(String(32), nullable=False, default="backward")


class SystemConfigModel(TimestampMixin, Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventOutboxModel(Base):
    __tablename__ = "event_outbox"
    __table_args__ = (UniqueConstraint("event_id", "topic", name="uq_event_outbox_event_topic"),)

    outbox_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_ingestion_log.event_id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketTradeModel(Base):
    __tablename__ = "market_trades"

    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="LIVE")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_sequence: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str | None] = mapped_column(String(16))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replay_session_id: Mapped[str | None] = mapped_column(String(128), index=True)


class MarketCandleModel(Base):
    __tablename__ = "market_candles"

    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="LIVE")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    candle_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_sequence: Mapped[int | None] = mapped_column(Integer)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replay_session_id: Mapped[str | None] = mapped_column(String(128), index=True)


class OrderBookSnapshotModel(Base):
    __tablename__ = "orderbook_snapshots"

    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="LIVE")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    update_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_sequence: Mapped[int | None] = mapped_column(Integer)
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    bids_json: Mapped[list[list[float]]] = mapped_column(JSONB, default=list)
    asks_json: Mapped[list[list[float]]] = mapped_column(JSONB, default=list)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replay_session_id: Mapped[str | None] = mapped_column(String(128), index=True)


class OrderBookFeatureModel(Base):
    __tablename__ = "orderbook_features"

    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="LIVE")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    spread: Mapped[float | None] = mapped_column(Float)
    top_n_depth: Mapped[float | None] = mapped_column(Float)
    imbalance: Mapped[float | None] = mapped_column(Float)


class SocialPostModel(Base):
    __tablename__ = "social_posts"
    __table_args__ = (
        UniqueConstraint(
            "scope_id",
            "source",
            "source_post_id",
            name="uq_social_post_scope_source_id",
        ),
    )

    post_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, default="LIVE", index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    pseudonymous_author_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    hashtags_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    cashtags_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    urls_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    user_mentions_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reply_to: Mapped[str | None] = mapped_column(String(255))
    repost_of: Mapped[str | None] = mapped_column(String(255))
    engagement_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    replay_session_id: Mapped[str | None] = mapped_column(String(128), index=True)


class PostAssetMentionModel(Base):
    __tablename__ = "post_asset_mentions"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "start_offset",
            "end_offset",
            "resolver_version",
            name="uq_post_mention_span_resolver",
        ),
    )

    mention_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    post_id: Mapped[str] = mapped_column(
        ForeignKey("social_posts.post_id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mention_text: Mapped[str] = mapped_column(String(64), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_asset_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list)


class AssetAliasModel(Base):
    __tablename__ = "asset_aliases"

    alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alias_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    is_ambiguous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ResolverVersionModel(TimestampMixin, Base):
    __tablename__ = "resolver_versions"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class FeatureWindowModel(TimestampMixin, Base):
    __tablename__ = "feature_windows"
    __table_args__ = (
        UniqueConstraint(
            "scope_id",
            "asset_id",
            "window_start",
            "interval_seconds",
            name="uq_feature_window_identity",
        ),
    )

    feature_window_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, default="LIVE", index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)


class FeatureLineageModel(Base):
    __tablename__ = "feature_lineage"

    lineage_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    source_event_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_event_min_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_event_max_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class FeatureRevisionModel(Base):
    __tablename__ = "feature_revisions"

    feature_window_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_windows.feature_window_id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    lineage_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_lineage.lineage_id"), nullable=False
    )
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetBaselineModel(TimestampMixin, Base):
    __tablename__ = "asset_baselines"

    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True, default="LIVE")
    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    feature_schema_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    history_window_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    baseline_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ModelScoreModel(Base):
    __tablename__ = "model_scores"
    __table_args__ = (
        UniqueConstraint(
            "feature_window_id",
            "feature_revision",
            "model_version",
            name="uq_model_score_window_revision_version",
        ),
    )

    model_score_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feature_window_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_windows.feature_window_id"), nullable=False, index=True
    )
    feature_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    market_score: Mapped[float | None] = mapped_column(Float)
    social_score: Mapped[float | None] = mapped_column(Float)
    coordination_score: Mapped[float | None] = mapped_column(Float)
    temporal_score: Mapped[float | None] = mapped_column(Float)
    claim_risk: Mapped[float | None] = mapped_column(Float)
    legitimate_event_score: Mapped[float | None] = mapped_column(Float)
    fusion_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    missing_outputs_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ThresholdConfigModel(TimestampMixin, Base):
    __tablename__ = "threshold_configs"

    config_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class MarketRegimeModel(Base):
    __tablename__ = "market_regimes"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AssetLiquidityClassModel(TimestampMixin, Base):
    __tablename__ = "asset_liquidity_classes"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    liquidity_class: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
