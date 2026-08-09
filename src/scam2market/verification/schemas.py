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
    reliability: float = Field(ge=0, le=1)


class Claim(BaseModel):
    claim_id: UUID
    narrative_id: UUID
    asset_id: str
    claim_text: str
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
    verified_at: datetime


class VerificationSummary(BaseModel):
    narrative_id: UUID
    alert_time: datetime
    result: VerificationResult
    claim_risk: float = Field(ge=0, le=1)
    legitimate_event_score: float = Field(ge=0, le=1)
    claims: list[Claim]
    verifications: list[ClaimVerification]
