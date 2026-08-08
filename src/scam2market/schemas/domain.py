from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AssetType(StrEnum):
    crypto = "CRYPTO"
    equity = "EQUITY"
    synthetic = "SYNTHETIC"


class CampaignStage(StrEnum):
    normal = "NORMAL"
    early_social_seeding = "EARLY_SOCIAL_SEEDING"
    coordinated_amplification = "COORDINATED_AMPLIFICATION"
    market_pump = "MARKET_PUMP"
    distribution = "DISTRIBUTION"
    dump = "DUMP"
    post_event = "POST_EVENT"


class AlertSeverity(StrEnum):
    info = "INFO"
    watch = "WATCH"
    high = "HIGH"
    critical = "CRITICAL"


class AlertType(StrEnum):
    social_hype_surge = "SOCIAL_HYPE_SURGE"
    coordinated_promotion = "COORDINATED_PROMOTION"
    unverified_narrative = "UNVERIFIED_NARRATIVE"
    market_volume_anomaly = "MARKET_VOLUME_ANOMALY"
    market_price_anomaly = "MARKET_PRICE_ANOMALY"
    market_microstructure_anomaly = "MARKET_MICROSTRUCTURE_ANOMALY"
    cross_domain_manipulation_risk = "CROSS_DOMAIN_MANIPULATION_RISK"
    possible_dump_phase = "POSSIBLE_DUMP_PHASE"


class Asset(BaseModel):
    asset_id: str
    symbol: str
    name: str
    asset_type: AssetType
    exchange: str | None = None
    quote_asset: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketTrade(BaseModel):
    trade_id: str
    asset_id: str
    event_time: datetime
    price: float
    quantity: float
    side: str | None = None
    source: str


class MarketCandle(BaseModel):
    candle_id: str
    asset_id: str
    event_time: datetime
    interval_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


class OrderBookUpdate(BaseModel):
    update_id: str
    asset_id: str
    event_time: datetime
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    top_bid_depth: float | None = None
    top_ask_depth: float | None = None
    bids: list[tuple[float, float]] = Field(default_factory=list)
    asks: list[tuple[float, float]] = Field(default_factory=list)
    source: str


class SocialPost(BaseModel):
    post_id: str
    platform: str
    author_id: str
    event_time: datetime
    text: str
    language: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    cashtags: list[str] = Field(default_factory=list)
    user_mentions: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    reply_to: str | None = None
    repost_of: str | None = None
    engagement: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class AssetMention(BaseModel):
    post_id: str
    asset_id: str | None
    mention_text: str
    start_offset: int
    end_offset: int
    confidence: float = Field(ge=0.0, le=1.0)
    resolver_version: str
    resolution_status: str = "RESOLVED"
    candidate_asset_ids: list[str] = Field(default_factory=list)


class Disclosure(BaseModel):
    disclosure_id: str
    source: str
    event_time: datetime
    title: str
    body: str
    url: str | None = None


class FeatureWindow(BaseModel):
    feature_window_id: UUID
    scope_id: str = "LIVE"
    asset_id: str
    window_start: datetime
    window_end: datetime
    interval_seconds: int
    revision: int = Field(ge=1)
    is_final: bool
    feature_schema_version: str
    features: dict[str, float | int | str | None]


class Narrative(BaseModel):
    narrative_id: UUID
    asset_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    label: str
    summary: str | None = None
    velocity: float | None = None


class GraphSnapshot(BaseModel):
    graph_snapshot_id: UUID
    asset_id: str
    window_start: datetime
    window_end: datetime
    graph_version: str
    features: dict[str, float | int | str | None]


class ModelScore(BaseModel):
    model_score_id: UUID
    asset_id: str
    feature_window_id: UUID
    model_name: str
    model_version: str
    score_name: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    scored_at: datetime


class Campaign(BaseModel):
    campaign_id: UUID
    asset_id: str
    stage: CampaignStage
    risk_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    started_at: datetime
    updated_at: datetime


class Alert(BaseModel):
    alert_id: UUID
    campaign_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    risk_score: float = Field(ge=0.0, le=100.0)
    evidence_revision: int = Field(ge=1)
    created_at: datetime


class EvidenceSnapshot(BaseModel):
    evidence_snapshot_id: UUID
    alert_id: UUID
    revision: int = Field(ge=1)
    feature_snapshot_id: UUID | None = None
    source_event_min_time: datetime
    source_event_max_time: datetime
    source_count: int = Field(ge=0)
    source_hash: str
    evidence: dict[str, Any]


class Investigation(BaseModel):
    investigation_id: UUID
    alert_id: UUID
    status: str
    analyst_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ReplaySession(BaseModel):
    replay_session_id: UUID
    dataset_id: str
    speed_multiplier: float = Field(gt=0)
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
