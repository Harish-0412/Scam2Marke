from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReplayStatus(StrEnum):
    created = "CREATED"
    running = "RUNNING"
    paused = "PAUSED"
    completed = "COMPLETED"
    failed = "FAILED"
    cancelled = "CANCELLED"


class ReplayCreate(BaseModel):
    scenario_id: str = "synthetic-pump-v1"
    speed_multiplier: float = Field(default=0.0, ge=0, le=10_000)
    random_seed: int | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class ScoreObservation(BaseModel):
    score_id: UUID
    event_time: datetime
    scored_at: datetime
    severity: str
    confidence: float = Field(ge=0, le=1)
    components: dict[str, float | None]
    missing_output_count: int = Field(ge=0)
    data_freshness_seconds: float | None = Field(default=None, ge=0)
    processing_latency_ms: float = Field(default=0, ge=0)


class EvaluationMetrics(BaseModel):
    observation_count: int
    alert_count: int
    watch_or_higher_count: int
    first_watch_at: datetime | None
    first_high_at: datetime | None
    first_critical_at: datetime | None
    lead_time_seconds: float | None
    hard_negative_precision_proxy: float
    false_positive_rate: float
    mean_confidence: float
    missing_output_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_data_freshness_seconds: float | None
    peak_score: float


class AblationResult(BaseModel):
    profile: str
    components: list[str]
    metrics: EvaluationMetrics
    contribution_delta: float


class ReplayEvaluation(BaseModel):
    evaluation_id: UUID
    replay_session_id: UUID
    evaluation_version: str
    manifest_hash: str
    metrics: EvaluationMetrics
    ablations: list[AblationResult]
    generated_at: datetime
    mlflow_run_id: str | None = None


class ModelArtifactCreate(BaseModel):
    model_family: str = Field(min_length=2, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    artifact_uri: str = Field(min_length=3, max_length=2000)
    artifact_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    input_schema_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    training_data_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    mlflow_run_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AliasAssignment(BaseModel):
    model_artifact_id: UUID
    reason: str = Field(min_length=5, max_length=2000)


class ShadowScoreRequest(BaseModel):
    model_artifact_id: UUID
    feature_window_id: UUID
    feature_revision: int = Field(ge=1)
    latency_ms: float = Field(default=0, ge=0)
