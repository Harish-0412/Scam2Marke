from functools import lru_cache
from typing import Annotated, Any, Literal, cast

from pydantic import AnyUrl, Field, SecretStr, field_validator
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
    kafka_security_protocol: Literal["PLAINTEXT", "SSL"] = "PLAINTEXT"

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
    disclosure_connector_poll_interval_seconds: float = Field(default=300, ge=5, le=86400)
    disclosure_connector_timeout_seconds: float = Field(default=15, gt=0, le=120)
    realtime_stream_key: str = "stream:alerts:v1"
    realtime_stream_max_length: int = Field(default=10_000, ge=100)
    mlflow_tracking_uri: AnyUrl | str = "http://localhost:5000"
    mlflow_enabled: bool = True
    mlflow_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    otel_exporter_otlp_endpoint: str | None = None
    dependency_probe_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    circuit_recovery_seconds: float = Field(default=30.0, gt=0, le=600)
    stream_batch_size: int = Field(default=50, ge=1, le=1000)
    stream_batch_wait_seconds: float = Field(default=0.25, gt=0, le=10)
    rate_limit_enabled: bool = True
    rate_limit_capacity: int = Field(default=300, ge=1, le=100_000)
    rate_limit_refill_per_second: float = Field(default=5.0, gt=0, le=10_000)
    rate_limit_fail_closed: bool = False
    service_api_key: str | None = None
    require_api_key: bool = False
    auth_required: bool = False
    development_auth_enabled: bool = True
    default_tenant_id: str = "default"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    service_key_pepper: str = "development-only-service-key-pepper"
    service_key_default_ttl_days: int = Field(default=90, ge=1, le=365)
    notification_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    calibration_min_samples: int = Field(default=20, ge=10, le=100_000)
    calibration_max_ece: float = Field(default=0.12, ge=0, le=1)
    calibration_min_auc: float = Field(default=0.65, ge=0, le=1)
    promotion_max_false_positives: int = Field(default=5, ge=0, le=100_000)
    promotion_brier_tolerance: float = Field(default=0.01, ge=0, le=1)
    otx_api_key: SecretStr | None = None
    otx_base_url: str = "https://otx.alienvault.com/api/v1/"
    otx_poll_interval_seconds: float = Field(default=300, ge=30, le=86400)
    otx_timeout_seconds: float = Field(default=15, gt=0, le=120)
    otx_page_size: int = Field(default=100, ge=1, le=500)
    otx_max_pages: int = Field(default=5, ge=1, le=50)
    otx_max_records: int = Field(default=1000, ge=1, le=10000)
    otx_max_response_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    threat_freshness_seconds: int = Field(default=86400, ge=60)
    threat_uplift_cap: float = Field(default=0.10, ge=0, le=0.25)

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
    market_provider: str = "synthetic"
    live_market_symbols: Annotated[list[str], NoDecode] = ["BTCUSDT"]
    binance_base_url: str = "https://api.binance.com"
    market_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    social_provider: str = "synthetic"
    mastodon_base_url: str = "https://mastodon.social"
    mastodon_access_token: str | None = None
    social_rss_urls: Annotated[list[str], NoDecode] = []
    social_poll_interval_seconds: float = Field(default=15.0, ge=1, le=900)

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

    @field_validator("live_market_symbols", "social_rss_urls", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return cast(list[str], value)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
