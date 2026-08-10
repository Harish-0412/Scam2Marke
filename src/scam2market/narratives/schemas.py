from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectionStatus(StrEnum):
    complete = "COMPLETE"
    degraded = "DEGRADED"


class NarrativePost(BaseModel):
    post_id: str
    scope_id: str
    asset_id: str
    author_id: str
    event_time: datetime
    text: str
    platform: str = "unknown"
    source: str = "social"
    language: str = "und"
    ingested_at: datetime | None = None
    hashtags: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    reply_to: str | None = None
    repost_of: str | None = None
    vector: list[float] = Field(default_factory=list)


class NarrativeCluster(BaseModel):
    narrative_id: UUID
    narrative_revision_id: UUID
    revision: int = Field(default=1, ge=1)
    cluster_key: str
    stable_key: str
    member_hash: str
    scope_id: str
    asset_id: str
    window_start: datetime
    window_end: datetime
    first_seen: datetime
    last_seen: datetime
    label: str
    summary: str
    post_ids: list[str]
    similarities: dict[str, float]
    unique_author_count: int
    centroid: list[float]
    embedding_version: str


class GraphFeatures(BaseModel):
    community_concentration: float = Field(ge=0, le=1)
    synchronized_posting: float = Field(ge=0, le=1)
    repeated_amplifier_overlap: float = Field(ge=0, le=1)
    propagation_depth: int = Field(ge=0)
    community_entropy: float = Field(ge=0, le=1)
    time_to_10_authors_seconds: float | None = Field(default=None, ge=0)
    authors_10_threshold_reached: bool = False
    time_to_100_authors_seconds: float | None = Field(default=None, ge=0)
    authors_100_threshold_reached: bool = False
    cross_community_spread: float = Field(ge=0, le=1)
    node_similarity: float = Field(ge=0, le=1)
    graph_score: float | None = Field(default=None, ge=0, le=1)


class GraphSnapshot(BaseModel):
    graph_snapshot_id: UUID
    scope_id: str
    asset_id: str
    feature_window_id: UUID
    feature_revision: int
    window_start: datetime
    window_end: datetime
    cutoff_event_time: datetime
    source_lineage_hash: str
    projection_version: str
    projection_status: ProjectionStatus
    node_count: int
    relationship_count: int
    error_message: str | None = None
    component_statuses: dict[str, str]
    features: GraphFeatures
    computed_at: datetime
