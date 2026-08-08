from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SignalKind(StrEnum):
    market_trade = "MARKET_TRADE"
    market_candle = "MARKET_CANDLE"
    orderbook = "ORDERBOOK"
    social_post = "SOCIAL_POST"
    asset_mention = "ASSET_MENTION"
    data_quality = "DATA_QUALITY"


class FeatureSignal(BaseModel):
    event_id: str
    scope_id: str = "LIVE"
    asset_id: str
    event_time: datetime
    ingested_at: datetime
    kind: SignalKind
    values: dict[str, Any] = Field(default_factory=dict)


class FeatureLineage(BaseModel):
    lineage_id: UUID
    source_event_ids: list[str]
    source_event_min_time: datetime | None
    source_event_max_time: datetime | None
    source_count: int = Field(ge=0)
    source_hash: str


FEATURE_NAMES: tuple[str, ...] = (
    "price_return",
    "volume",
    "relative_volume",
    "volatility",
    "spread",
    "top_n_depth",
    "orderbook_imbalance",
    "trade_count",
    "buy_sell_pressure",
    "market_data_freshness_seconds",
    "mention_count",
    "unique_author_count",
    "author_concentration",
    "repost_reply_ratio",
    "hashtag_velocity",
    "url_concentration",
    "new_author_ratio",
    "social_data_freshness_seconds",
    "social_lead_seconds",
    "source_gap_count",
    "data_quality_score",
    "baseline_confidence",
)


class FeatureSnapshot(BaseModel):
    feature_window_id: UUID
    scope_id: str = "LIVE"
    asset_id: str
    window_start: datetime
    window_end: datetime
    interval_seconds: int
    revision: int = Field(ge=1)
    is_final: bool
    feature_schema_version: str
    features: dict[str, float | int | None]
    lineage: FeatureLineage

    @model_validator(mode="after")
    def feature_order_matches_schema(self) -> "FeatureSnapshot":
        if tuple(self.features) != FEATURE_NAMES:
            raise ValueError("feature names are missing, extra, or reordered")
        return self


class ModelInput(BaseModel):
    feature_schema_version: str
    feature_names: list[str]
    values: list[float | int | None]

    @model_validator(mode="after")
    def validate_exact_schema(self) -> "ModelInput":
        if tuple(self.feature_names) != FEATURE_NAMES:
            raise ValueError("model input feature order does not match the registered schema")
        if len(self.values) != len(FEATURE_NAMES):
            raise ValueError("model input value count does not match feature count")
        return self

    @classmethod
    def from_snapshot(cls, snapshot: FeatureSnapshot) -> "ModelInput":
        return cls(
            feature_schema_version=snapshot.feature_schema_version,
            feature_names=list(snapshot.features),
            values=list(snapshot.features.values()),
        )
