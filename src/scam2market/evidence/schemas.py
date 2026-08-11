from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceReference(BaseModel):
    evidence_type: str
    evidence_id: str
    event_time: datetime | None = None
    digest: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceInput(BaseModel):
    alert_id: UUID
    campaign_id: UUID
    scope_id: str
    asset_id: str
    alert_version: int
    alert_type: str
    severity: str
    stage: str
    evidence_cutoff: datetime
    campaign_evidence_event_id: str
    fusion: dict[str, Any]
    feature: dict[str, Any] | None = None
    feature_lineage: dict[str, Any] | None = None
    narrative: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None
    verifications: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceSnapshot(BaseModel):
    snapshot_id: UUID
    alert_id: UUID
    campaign_id: UUID
    scope_id: str
    asset_id: str
    alert_version: int
    evidence_cutoff: datetime
    schema_version: str
    content: dict[str, Any]
    content_hash: str
    previous_chain_hash: str | None
    chain_hash: str
    completeness_score: float = Field(ge=0, le=1)
    completeness: dict[str, Any]
    references: list[EvidenceReference]
    created_at: datetime


class DeterministicExplanation(BaseModel):
    explanation_id: UUID
    snapshot_id: UUID
    template_version: str
    summary: str
    triggered_rules: list[dict[str, Any]]
    contributors: list[dict[str, Any]]
    context: dict[str, Any]
    llm_summary: str | None = None
    llm_status: str = "NOT_REQUESTED"
    generated_at: datetime


class InvestigationStatus(StrEnum):
    open = "OPEN"
    triage = "TRIAGE"
    investigating = "INVESTIGATING"
    awaiting_review = "AWAITING_REVIEW"
    closed = "CLOSED"


class InvestigationPriority(StrEnum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"
    urgent = "URGENT"


class FeedbackLabel(StrEnum):
    true_positive = "TRUE_POSITIVE"
    false_positive = "FALSE_POSITIVE"
    legitimate_event = "LEGITIMATE_EVENT"
    insufficient_evidence = "INSUFFICIENT_EVIDENCE"
    needs_monitoring = "NEEDS_MONITORING"


class InvestigationCreate(BaseModel):
    alert_id: UUID
    snapshot_id: UUID
    title: str = Field(min_length=3, max_length=255)
    priority: InvestigationPriority = InvestigationPriority.medium
    assigned_to: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=20)
    sla_hours: int = Field(default=24, ge=1, le=720)


class InvestigationUpdate(BaseModel):
    status: InvestigationStatus | None = None
    priority: InvestigationPriority | None = None
    assigned_to: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=20)
    disposition: str | None = Field(default=None, max_length=64)
    expected_version: int = Field(ge=1)


class InvestigationEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)


class FeedbackCreate(BaseModel):
    label: FeedbackLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=10, max_length=4000)


class FeedbackAdjudication(BaseModel):
    accepted: bool
    note: str = Field(min_length=3, max_length=4000)
