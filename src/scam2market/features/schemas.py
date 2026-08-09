from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from scam2market.features.manifest import load_feature_manifest


class SignalKind(StrEnum):
    market_trade = "MARKET_TRADE"
    market_candle = "MARKET_CANDLE"
    orderbook = "ORDERBOOK"
    social_post = "SOCIAL_POST"
    asset_mention = "ASSET_MENTION"
    data_quality = "DATA_QUALITY"


class SourceDomain(StrEnum):
    market = "market"
    social = "social"


class RevisionState(StrEnum):
    provisional = "PROVISIONAL"
    final = "FINAL"
    corrected = "CORRECTED"


class FeatureSignal(BaseModel):
    event_id: str
    scope_id: str = "LIVE"
    asset_id: str
    event_time: datetime
    ingested_at: datetime
    kind: SignalKind
    source_domain: SourceDomain
    values: dict[str, Any] = Field(default_factory=dict)


class FeatureLineage(BaseModel):
    lineage_id: UUID
    source_event_ids: list[str]
    source_event_min_time: datetime | None
    source_event_max_time: datetime | None
    source_count: int = Field(ge=0)
    source_hash: str


FEATURE_SCHEMA = load_feature_manifest()
FEATURE_NAMES: tuple[str, ...] = tuple(FEATURE_SCHEMA.ordered_features)


class FeatureSnapshot(BaseModel):
    feature_window_id: UUID
    scope_id: str = "LIVE"
    asset_id: str
    window_start: datetime
    window_end: datetime
    interval_seconds: int
    revision: int = Field(ge=1)
    is_final: bool
    revision_state: RevisionState = RevisionState.provisional
    supersedes_revision: int | None = Field(default=None, ge=1)
    feature_schema_version: str
    feature_schema_hash: str = FEATURE_SCHEMA.schema_hash
    features: dict[str, float | int | None]
    lineage: FeatureLineage

    @model_validator(mode="after")
    def feature_order_matches_schema(self) -> "FeatureSnapshot":
        if tuple(self.features) != FEATURE_NAMES:
            raise ValueError("feature names are missing, extra, or reordered")
        if self.feature_schema_version != FEATURE_SCHEMA.feature_schema:
            raise ValueError("feature schema version does not match the registered manifest")
        if self.feature_schema_hash != FEATURE_SCHEMA.schema_hash:
            raise ValueError("feature schema hash does not match the registered manifest")
        if self.is_final != (self.revision_state != RevisionState.provisional):
            raise ValueError("is_final and revision_state disagree")
        if self.revision_state == RevisionState.corrected and self.supersedes_revision is None:
            raise ValueError("corrected revisions must identify the superseded revision")
        return self


class ModelInput(BaseModel):
    feature_schema_version: str
    feature_schema_hash: str
    feature_names: list[str]
    values: list[float | int | None]

    @model_validator(mode="after")
    def validate_exact_schema(self) -> "ModelInput":
        if tuple(self.feature_names) != FEATURE_NAMES:
            raise ValueError("model input feature order does not match the registered schema")
        if len(self.values) != len(FEATURE_NAMES):
            raise ValueError("model input value count does not match feature count")
        if self.feature_schema_hash != FEATURE_SCHEMA.schema_hash:
            raise ValueError("model input schema hash does not match the registered schema")
        return self

    @classmethod
    def from_snapshot(cls, snapshot: FeatureSnapshot) -> "ModelInput":
        return cls(
            feature_schema_version=snapshot.feature_schema_version,
            feature_schema_hash=snapshot.feature_schema_hash,
            feature_names=list(FEATURE_NAMES),
            values=[snapshot.features[name] for name in FEATURE_NAMES],
        )
