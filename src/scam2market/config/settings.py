from functools import lru_cache
from typing import Annotated, Any, cast

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Scam2Market Backend"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://scam2market:scam2market@localhost:5432/scam2market"
    )
    redis_url: str = "redis://localhost:6379/0"
    redpanda_bootstrap_servers: str = "localhost:19092"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "scam2market-password"

    qdrant_url: AnyUrl | str = "http://localhost:6333"
    qdrant_post_collection: str = "social-post-embeddings-v1"
    qdrant_disclosure_collection: str = "disclosure-chunks-v1"
    embedding_dimensions: int = Field(default=128, ge=32, le=4096)
    narrative_similarity_threshold: float = Field(default=0.76, ge=0, le=1)
    narrative_window_seconds: int = Field(default=300, gt=0)
    campaign_merge_gap_seconds: int = Field(default=1800, gt=0)
    alert_suppression_seconds: int = Field(default=300, ge=0)
    campaign_lock_retry_count: int = Field(default=3, ge=0, le=20)
    campaign_lock_retry_backoff_ms: int = Field(default=50, ge=1, le=5000)
    campaign_inactivity_close_seconds: int = Field(default=3600, gt=0)
    verification_pre_alert_lookback_days: int = Field(default=30, gt=0)
    verification_post_alert_horizon_days: int = Field(default=7, ge=0)
    realtime_stream_key: str = "stream:alerts:v1"
    realtime_stream_max_length: int = Field(default=10_000, ge=100)
    mlflow_tracking_uri: AnyUrl | str = "http://localhost:5000"

    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    raw_archive_path: str = "./data/raw"
    author_pseudonymization_key: str = "development-only-change-me"
    author_pseudonymization_key_version: int = Field(default=1, ge=1)
    market_freshness_threshold_seconds: int = Field(default=30, gt=0)
    social_freshness_threshold_seconds: int = Field(default=300, gt=0)
    feature_allowed_lateness_seconds: int = Field(default=120, ge=0)
    feature_window_intervals_seconds: Annotated[list[int], NoDecode] = [60, 300]
    feature_source_idle_after_seconds: int = Field(default=300, gt=0)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return cast(list[str], value)

    @field_validator("feature_window_intervals_seconds", mode="before")
    @classmethod
    def parse_feature_intervals(cls, value: Any) -> list[int]:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return cast(list[int], value)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
