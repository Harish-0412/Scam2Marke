from datetime import datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(StrEnum):
    market_trade_received = "market.trade.received"
    market_candle_closed = "market.candle.closed"
    market_orderbook_updated = "market.orderbook.updated"
    social_post_received = "social.post.received"
    social_post_normalized = "social.post.normalized"
    social_asset_mention_detected = "social.asset_mention.detected"
    disclosure_received = "disclosure.received"
    feature_window_updated = "feature.window_updated"
    feature_window_finalized = "feature.window_finalized"
    model_fusion_scored = "model.fusion_scored"
    campaign_created = "campaign.created"
    campaign_stage_changed = "campaign.stage_changed"
    alert_created = "alert.created"
    alert_severity_changed = "alert.severity_changed"


class ReplayMetadata(BaseModel):
    is_replay: bool = False
    replay_session_id: str | None = None

    @model_validator(mode="after")
    def replay_session_required_for_replay(self) -> Self:
        if self.is_replay and not self.replay_session_id:
            raise ValueError("replay_session_id is required when is_replay is true")
        return self


class TraceMetadata(BaseModel):
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None


class CanonicalEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    schema_version: int = Field(ge=1)
    source: str
    source_event_id: str
    source_sequence: int | None = None
    asset_id: str | None = None
    event_time: datetime
    ingested_at: datetime
    processed_at: datetime | None = None
    partition_key: str
    replay: ReplayMetadata = Field(default_factory=ReplayMetadata)
    trace: TraceMetadata = Field(default_factory=TraceMetadata)
    payload: dict[str, Any]

    @field_validator("partition_key")
    @classmethod
    def partition_key_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("partition_key cannot be blank")
        return value

    @field_validator("source", "source_event_id")
    @classmethod
    def required_string_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value

    def dedupe_key(self) -> str:
        if self.replay.is_replay and self.replay.replay_session_id:
            return f"replay:{self.replay.replay_session_id}:{self.source_event_id}"
        return f"{self.source}:{self.source_event_id}"
