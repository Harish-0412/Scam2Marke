from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from scam2market.intelligence.fusion import FusionResult, RiskLevel


class CampaignStage(StrEnum):
    normal = "NORMAL"
    early_social_seeding = "EARLY_SOCIAL_SEEDING"
    coordinated_amplification = "COORDINATED_AMPLIFICATION"
    market_pump = "MARKET_PUMP"
    possible_distribution = "POSSIBLE_DISTRIBUTION"
    dump = "DUMP"
    post_event = "POST_EVENT"


class CampaignStatus(StrEnum):
    active = "ACTIVE"
    closed = "CLOSED"


class AlertStatus(StrEnum):
    active = "ACTIVE"
    resolved = "RESOLVED"


class AlertType(StrEnum):
    social_hype_surge = "SOCIAL_HYPE_SURGE"
    coordinated_promotion = "COORDINATED_PROMOTION"
    unverified_narrative = "UNVERIFIED_NARRATIVE"
    market_volume_anomaly = "MARKET_VOLUME_ANOMALY"
    market_price_anomaly = "MARKET_PRICE_ANOMALY"
    market_microstructure_anomaly = "MARKET_MICROSTRUCTURE_ANOMALY"
    cross_domain_manipulation_risk = "CROSS_DOMAIN_MANIPULATION_RISK"
    possible_dump_phase = "POSSIBLE_DUMP_PHASE"


class CampaignEvidence(BaseModel):
    event_id: str
    correlation_id: str
    causation_id: str | None = None
    event_time: datetime
    fusion: FusionResult

    @property
    def scope_id(self) -> str:
        return self.fusion.scope_id

    @property
    def asset_id(self) -> str:
        return self.fusion.asset_id


class AlertTrigger(BaseModel):
    alert_type: AlertType
    severity: RiskLevel
    reason: str


class CampaignAssessment(BaseModel):
    next_stage: CampaignStage
    transition_reason: str
    stage_confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    stage_evidence_ids: list[str] = Field(default_factory=list)
    rule_version: str = "campaign-stage-rules-v2"
    alerts: list[AlertTrigger] = Field(default_factory=list)


class CampaignRecord(BaseModel):
    campaign_id: UUID
    scope_id: str
    asset_id: str
    stage: CampaignStage
    stage_confidence: float = Field(default=0.0, ge=0, le=1)
    stage_reason: dict[str, object] = Field(default_factory=dict)
    status: CampaignStatus
    max_severity: RiskLevel
    first_evidence_at: datetime
    last_evidence_at: datetime
    last_applied_evidence_cutoff: datetime | None = None
    last_applied_feature_revision: int = 0
    last_applied_fusion_revision: int = 0
    last_applied_enrichment_profile: str = "BASE"
    version: int


class AlertRecord(BaseModel):
    alert_id: UUID
    campaign_id: UUID
    alert_type: AlertType
    severity: RiskLevel
    status: AlertStatus
    first_triggered_at: datetime
    last_triggered_at: datetime
    last_notified_at: datetime | None
    occurrence_count: int
    version: int


class CampaignUpdate(BaseModel):
    campaign: CampaignRecord
    alerts: list[AlertRecord] = Field(default_factory=list)
    duplicate_evidence: bool = False
    stale_evidence: bool = False
    emitted_event_ids: list[str] = Field(default_factory=list)
