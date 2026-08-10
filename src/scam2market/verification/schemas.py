from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class VerificationResult(StrEnum):
    supported_before_alert = "SUPPORTED_BEFORE_ALERT"
    supported_after_alert = "SUPPORTED_AFTER_ALERT"
    unsupported = "UNSUPPORTED"
    conflicting = "CONFLICTING"
    unknown = "UNKNOWN"


class DisclosureDocument(BaseModel):
    disclosure_id: UUID
    source: str
    source_document_id: str
    asset_id: str | None = None
    title: str
    body: str
    url: str | None = None
    published_at: datetime
    retrieved_at: datetime
    first_observed_at: datetime | None = None
    ingested_at: datetime | None = None
    document_version: int = Field(default=1, ge=1)
    supersedes_disclosure_id: UUID | None = None
    source_policy_version: str = "official-sources-v1"
    reliability: float = Field(default=1.0, ge=0, le=1)
    content_hash: str


class DisclosureChunk(BaseModel):
    chunk_id: UUID
    disclosure_id: UUID
    chunk_index: int = Field(ge=0)
    text: str
    token_count: int = Field(ge=0)
    embedding_version: str
    metadata: dict[str, str]


class DisclosureCandidate(BaseModel):
    chunk_id: UUID
    disclosure_id: UUID
    source: str
    source_document_id: str
    title: str
    text: str
    published_at: datetime
    first_observed_at: datetime
    document_version: int = Field(ge=1)
    source_policy_version: str
    reliability: float = Field(ge=0, le=1)


class Claim(BaseModel):
    claim_id: UUID
    narrative_id: UUID
    asset_id: str
    claim_text: str
    claim_type: str = "OTHER"
    canonical_payload: dict[str, object] = Field(default_factory=dict)
    claim_hash: str
    extracted_at: datetime
    extractor_version: str


class ClaimVerification(BaseModel):
    verification_id: UUID
    claim_id: UUID
    alert_time: datetime
    result: VerificationResult
    claim_risk: float = Field(ge=0, le=1)
    legitimate_event_score: float = Field(ge=0, le=1)
    evidence_document_ids: list[str]
    retrieval_metadata: dict[str, object]
    deterministic_reason: str
    llm_explanation: str | None = None
    verifier_version: str
    source_policy_version: str = "official-sources-v1"
    retrospective_only: bool = False
    verified_at: datetime


class VerificationSummary(BaseModel):
    verification_snapshot_id: UUID
    narrative_id: UUID
    alert_time: datetime
    result: VerificationResult
    claim_risk: float = Field(ge=0, le=1)
    legitimate_event_score: float = Field(ge=0, le=1)
    claims: list[Claim]
    verifications: list[ClaimVerification]
