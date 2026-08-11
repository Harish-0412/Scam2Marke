from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
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
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    virtual_clock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str | None] = mapped_column(String(128))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventIngestionLogModel(Base):
    __tablename__ = "event_ingestion_log"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_event_ingestion_dedupe_key"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origin_event_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    delivery_event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
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
    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("event_id", "topic", name="uq_outbox_event_topic"),)

    outbox_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerCheckpointModel(Base):
    __tablename__ = "worker_checkpoints"

    consumer_group: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), primary_key=True)
    partition: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_durable_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    feature_state_version: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    orderbook_state: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID")
    book_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    book_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
    pseudonym_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    resolution_reason: Mapped[str] = mapped_column(String(128), nullable=False)


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
    revision_state: Mapped[str] = mapped_column(String(32), nullable=False, default="PROVISIONAL")
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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
    revision_state: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_revision: Mapped[int | None] = mapped_column(Integer)
    feature_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_model_score_idempotency_key"),)

    model_score_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feature_window_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_windows.feature_window_id"), nullable=False, index=True
    )
    feature_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    base_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fusion_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    enrichment_profile: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fusion_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_snapshot_ids_json: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    market_score: Mapped[float | None] = mapped_column(Float)
    social_score: Mapped[float | None] = mapped_column(Float)
    coordination_score: Mapped[float | None] = mapped_column(Float)
    temporal_score: Mapped[float | None] = mapped_column(Float)
    claim_risk: Mapped[float | None] = mapped_column(Float)
    legitimate_event_score: Mapped[float | None] = mapped_column(Float)
    graph_score: Mapped[float | None] = mapped_column(Float)
    market_anomaly_risk: Mapped[float | None] = mapped_column(Float)
    market_anomaly_severity: Mapped[str] = mapped_column(String(32), nullable=False)
    social_coordination_risk: Mapped[float | None] = mapped_column(Float)
    social_coordination_severity: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_cross_domain_risk: Mapped[float] = mapped_column(Float, nullable=False)
    context_adjusted_risk: Mapped[float] = mapped_column(Float, nullable=False)
    fusion_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    missing_outputs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    market_regime_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    liquidity_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    stage_signals_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
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


class CampaignModel(TimestampMixin, Base):
    __tablename__ = "campaigns"

    campaign_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, default="LIVE", index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="NORMAL")
    stage_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage_reason_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    stage_rule_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="campaign-stage-rules-v2"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    max_severity: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    first_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dominant_narrative_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    last_applied_evidence_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_applied_feature_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_applied_fusion_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_applied_enrichment_profile: Mapped[str] = mapped_column(
        String(32), nullable=False, default="BASE"
    )
    closed_reason: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CampaignEvidenceModel(Base):
    __tablename__ = "campaign_evidence"
    __table_args__ = (
        UniqueConstraint("scope_id", "evidence_event_id", name="uq_campaign_evidence_scope_event"),
    )

    evidence_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    campaign_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignStageHistoryModel(Base):
    __tablename__ = "campaign_stage_history"
    __table_args__ = (
        UniqueConstraint("campaign_id", "evidence_event_id", name="uq_campaign_stage_evidence"),
    )

    stage_history_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    campaign_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_stage: Mapped[str | None] = mapped_column(String(64))
    to_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_at_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertModel(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("campaign_id", "alert_type", name="uq_alert_campaign_type"),)

    alert_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    campaign_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AlertStateHistoryModel(Base):
    __tablename__ = "alert_state_history"
    __table_args__ = (
        UniqueConstraint("alert_id", "evidence_event_id", name="uq_alert_state_evidence"),
    )

    alert_history_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_severity: Mapped[str | None] = mapped_column(String(32))
    to_severity: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(128))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeModel(TimestampMixin, Base):
    __tablename__ = "narratives"
    __table_args__ = (
        UniqueConstraint("scope_id", "asset_id", "stable_key", name="uq_narrative_stable_key"),
    )

    narrative_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(255), nullable=False)
    current_revision_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    member_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_author_count: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid_json: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)


class NarrativeRevisionModel(Base):
    __tablename__ = "narrative_revisions"
    __table_args__ = (
        UniqueConstraint("narrative_id", "revision", name="uq_narrative_revision_number"),
        UniqueConstraint("narrative_id", "member_hash", name="uq_narrative_revision_members"),
    )

    narrative_revision_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    narrative_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("narratives.narrative_id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    member_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    centroid_json: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NarrativePostModel(Base):
    __tablename__ = "narrative_posts"

    narrative_revision_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("narrative_revisions.narrative_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    narrative_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("narratives.narrative_id", ondelete="CASCADE"), nullable=False, index=True
    )
    post_id: Mapped[str] = mapped_column(
        ForeignKey("social_posts.post_id", ondelete="CASCADE"), primary_key=True
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GraphSnapshotModel(Base):
    __tablename__ = "graph_snapshots"

    graph_snapshot_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    relationship_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    component_status_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphFeatureModel(Base):
    __tablename__ = "graph_features"

    graph_snapshot_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("graph_snapshots.graph_snapshot_id", ondelete="CASCADE"), primary_key=True
    )
    feature_window_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_windows.feature_window_id", ondelete="CASCADE"), nullable=False
    )
    feature_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_score: Mapped[float | None] = mapped_column(Float)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DisclosureModel(TimestampMixin, Base):
    __tablename__ = "disclosures"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_document_id", "document_version", name="uq_disclosure_version"
        ),
    )

    disclosure_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_disclosure_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("disclosures.disclosure_id", ondelete="SET NULL")
    )
    source_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reliability: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DisclosureChunkModel(Base):
    __tablename__ = "disclosure_chunks"

    chunk_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    disclosure_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("disclosures.disclosure_id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ClaimModel(TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("narrative_id", "claim_hash", name="uq_narrative_claim_hash"),
    )

    claim_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    narrative_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("narratives.narrative_id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    claim_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ClaimVerificationModel(Base):
    __tablename__ = "claim_verifications"
    __table_args__ = (
        UniqueConstraint(
            "claim_id", "alert_time", "verifier_version", name="uq_claim_verification_cutoff"
        ),
    )

    verification_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claim_risk: Mapped[float] = mapped_column(Float, nullable=False)
    legitimate_event_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_document_ids_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    retrieval_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deterministic_reason: Mapped[str] = mapped_column(Text, nullable=False)
    llm_explanation: Mapped[str | None] = mapped_column(Text)
    verifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retrospective_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# New models for Phase 9 enhancements
class ThreatIndicatorModel(TimestampMixin, Base):
    __tablename__ = "threat_indicators"

    indicator_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    indicator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExplainabilityOutputModel(TimestampMixin, Base):
    __tablename__ = "explainability_outputs"

    output_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    claim_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.claim_id"), nullable=False, index=True
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvidenceSnapshotModel(Base):
    __tablename__ = "evidence_snapshots"
    __table_args__ = (
        UniqueConstraint("alert_id", "alert_version", name="uq_evidence_alert_version"),
        UniqueConstraint("content_hash", name="uq_evidence_content_hash"),
    )

    snapshot_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campaign_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alert_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_chain_hash: Mapped[str | None] = mapped_column(String(64))
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False)
    completeness_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertEvidenceModel(Base):
    __tablename__ = "alert_evidence"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "evidence_type", "evidence_id", name="uq_snapshot_evidence_ref"
        ),
    )

    alert_evidence_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    snapshot_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ExplanationModel(Base):
    __tablename__ = "explanations"

    explanation_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    contributors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    llm_summary: Mapped[str | None] = mapped_column(Text)
    llm_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_REQUESTED")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InvestigationModel(TimestampMixin, Base):
    __tablename__ = "investigations"

    investigation_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM")
    assigned_to: Mapped[str | None] = mapped_column(String(128), index=True)
    tags_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    disposition: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_by: Mapped[str] = mapped_column(String(128), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationEventModel(Base):
    __tablename__ = "investigation_events"

    investigation_event_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    investigation_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("investigations.investigation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalystFeedbackModel(TimestampMixin, Base):
    __tablename__ = "analyst_feedback"

    feedback_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    investigation_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("investigations.investigation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    analyst_id: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    adjudicated_by: Mapped[str | None] = mapped_column(String(128))
    adjudicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjudication_note: Mapped[str | None] = mapped_column(Text)


class ReplayEvaluationModel(Base):
    __tablename__ = "replay_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "replay_session_id", "evaluation_version", name="uq_replay_evaluation_version"
        ),
    )

    evaluation_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    replay_session_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("replay_sessions.replay_session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evaluation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    mlflow_run_id: Mapped[str | None] = mapped_column(String(128))


class AblationResultModel(Base):
    __tablename__ = "ablation_results"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "profile", name="uq_evaluation_ablation_profile"),
    )

    ablation_result_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("replay_evaluations.evaluation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    component_set_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contribution_delta: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelArtifactModel(TimestampMixin, Base):
    __tablename__ = "model_artifacts"
    __table_args__ = (
        UniqueConstraint("model_family", "model_version", name="uq_model_family_version"),
    )

    model_artifact_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    model_family: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    training_data_hash: Mapped[str | None] = mapped_column(String(64))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="REGISTERED")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ModelAliasModel(Base):
    __tablename__ = "model_aliases"

    model_family: Mapped[str] = mapped_column(String(128), primary_key=True)
    alias: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_artifact_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShadowScoreModel(Base):
    __tablename__ = "shadow_scores"
    __table_args__ = (
        UniqueConstraint(
            "feature_window_id", "feature_revision", "model_artifact_id", name="uq_shadow_score"
        ),
    )

    shadow_score_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    replay_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("replay_sessions.replay_session_id", ondelete="SET NULL"), index=True
    )
    feature_window_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("feature_windows.feature_window_id", ondelete="CASCADE"), nullable=False
    )
    feature_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    model_artifact_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    champion_model_score_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("model_scores.model_score_id", ondelete="SET NULL")
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    controls_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agreement: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WatchlistModel(TimestampMixin, Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope_id", "name", name="uq_watchlist_owner_scope_name"),
    )

    watchlist_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, default="LIVE", index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WatchlistAssetModel(Base):
    __tablename__ = "watchlist_assets"

    watchlist_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("watchlists.watchlist_id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.asset_id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[str] = mapped_column(String(128), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertActionModel(Base):
    __tablename__ = "alert_actions"

    action_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    alert_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PolicyProposalModel(TimestampMixin, Base):
    __tablename__ = "policy_proposals"

    proposal_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    proposed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelDriftEventModel(Base):
    __tablename__ = "model_drift_events"

    drift_event_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    model_family: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    drift_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
