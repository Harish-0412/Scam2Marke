from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.db.models import (
    AlertModel,
    AuditLogModel,
    CampaignModel,
    ClaimModel,
    ClaimVerificationModel,
    DisclosureModel,
    NarrativeModel,
    SourceConnectorRunModel,
    SourcePolicyModel,
    VerificationEvidenceModel,
)
from scam2market.db.session import get_db_session
from scam2market.security.auth import CurrentPrincipal, require_permission

router = APIRouter()


class SourcePolicyInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_class: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    connector_type: str = Field(pattern="^(RSS_ATOM|GITHUB_RELEASES|SEC_EDGAR)$")
    connector_config: dict[str, Any]
    enabled: bool = True
    trust_score: float = Field(ge=0, le=1)
    trust_tier: str = Field(min_length=1, max_length=32)
    trust_rationale: str | None = None
    license_allowed_usages: list[str]
    license_retention_days: int | None = Field(default=None, ge=0)
    license_attribution: str | None = None
    license_display_allowed: bool = False
    policy_version: str = Field(min_length=1, max_length=64)
    canonical_domains: list[str]
    effective_from: datetime
    effective_to: datetime | None = None


class SourcePolicyPatch(BaseModel):
    policy_version: str = Field(min_length=1, max_length=64)
    enabled: bool | None = None
    connector_config: dict[str, Any] | None = None
    trust_score: float | None = Field(default=None, ge=0, le=1)
    trust_tier: str | None = None
    trust_rationale: str | None = None
    license_allowed_usages: list[str] | None = None
    license_retention_days: int | None = Field(default=None, ge=0)
    license_attribution: str | None = None
    license_display_allowed: bool | None = None
    effective_to: datetime | None = None


class SourcePolicyResponse(SourcePolicyInput):
    source_policy_id: UUID
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class TimelineEvent(BaseModel):
    event_type: str
    event_time: datetime
    data: dict[str, Any]


class ClaimResponse(BaseModel):
    claim_id: UUID
    narrative_id: UUID
    asset_id: str
    claim_text: str
    claim_type: str
    canonical_json: dict[str, Any]
    claim_hash: str
    extracted_at: datetime
    extractor_version: str


class DisclosureResponse(BaseModel):
    disclosure_id: UUID
    source: str
    source_document_id: str
    source_document_key: str | None
    source_policy_id: UUID | None
    connector_run_id: UUID | None
    asset_id: str | None
    title: str
    body: str | None
    url: str | None
    published_at: datetime
    retrieved_at: datetime
    first_observed_at: datetime
    ingested_at: datetime
    available_at: datetime
    document_version: int
    version_status: str
    supersedes_disclosure_id: UUID | None
    source_policy_version: str
    reliability: float
    content_hash: str
    etag: str | None
    last_modified: str | None
    signature_metadata_json: dict[str, Any]


class ConnectorRunResponse(BaseModel):
    connector_run_id: UUID
    source_policy_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    checkpoint_json: dict[str, Any]
    fetched_count: int
    ingested_count: int
    unchanged_count: int
    error_count: int
    lag_seconds: float | None
    error_json: dict[str, Any]
    source_watermark: datetime | None


class VerificationEvidenceResponse(BaseModel):
    verification_evidence_id: UUID
    verification_id: UUID
    disclosure_id: UUID
    relation: str
    score: float
    rank: int
    temporal_eligible: bool
    reason_codes_json: list[str]
    source_policy_id_snapshot: UUID | None
    source_policy_version_snapshot: str
    trust_score_snapshot: float
    trust_tier_snapshot: str
    license_snapshot_json: dict[str, Any]
    created_at: datetime


class ClaimVerificationResponse(BaseModel):
    verification_id: UUID
    claim_id: UUID
    alert_time: datetime
    result: str
    claim_risk: float
    legitimate_event_score: float
    evidence_document_ids_json: list[str]
    retrieval_metadata_json: dict[str, Any]
    deterministic_reason: str
    llm_explanation: str | None
    verifier_version: str
    source_policy_version: str
    retrospective_only: bool
    verified_at: datetime
    evidence: list[VerificationEvidenceResponse]


@router.get("/source-policies", response_model=list[SourcePolicyResponse])
async def source_policies(session: AsyncSession = Depends(get_db_session)) -> list[dict[str, Any]]:
    rows = (await session.scalars(select(SourcePolicyModel).order_by(SourcePolicyModel.name))).all()
    return [_policy(row) for row in rows]


@router.post(
    "/source-policies",
    response_model=SourcePolicyResponse,
    status_code=201,
    dependencies=[Depends(require_permission("source-policy:manage"))],
)
async def create_source_policy(
    body: SourcePolicyInput,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _validate_policy_domains(body.connector_type, body.canonical_domains)
    now = datetime.now(tz=UTC)
    _validate_policy_window(body.effective_from, body.effective_to, now)
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(body.name, 0))))
    overlap_query = select(SourcePolicyModel.source_policy_id).where(
        SourcePolicyModel.name == body.name,
        (SourcePolicyModel.effective_to.is_(None))
        | (SourcePolicyModel.effective_to > body.effective_from),
    )
    if body.effective_to is not None:
        overlap_query = overlap_query.where(SourcePolicyModel.effective_from < body.effective_to)
    overlapping = await session.scalar(overlap_query)
    if overlapping is not None:
        raise HTTPException(
            status_code=409,
            detail="an overlapping policy exists for this source; create a replacement with PATCH",
        )
    row = SourcePolicyModel(
        **_policy_columns(body.model_dump()),
        created_by=principal.subject,
        updated_by=principal.subject,
    )
    session.add(row)
    await session.flush()
    session.add(
        AuditLogModel(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action="source_policy.created",
            target_type="source_policy",
            target_id=str(row.source_policy_id),
            metadata_json={"name": row.name, "policy_version": row.policy_version},
        )
    )
    await session.commit()
    await session.refresh(row)
    return _policy(row)


@router.patch(
    "/source-policies/{source_policy_id}",
    response_model=SourcePolicyResponse,
    dependencies=[Depends(require_permission("source-policy:manage"))],
)
async def patch_source_policy(
    source_policy_id: UUID,
    body: SourcePolicyPatch,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await session.get(SourcePolicyModel, source_policy_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="source policy not found")
    changed_at = datetime.now(tz=UTC)
    if row.effective_to is not None and row.effective_to <= changed_at:
        raise HTTPException(status_code=409, detail="historical source policy cannot be patched")
    if body.policy_version == row.policy_version:
        raise HTTPException(status_code=409, detail="replacement policy_version must be new")
    if await session.scalar(
        select(SourcePolicyModel.source_policy_id).where(
            SourcePolicyModel.name == row.name,
            SourcePolicyModel.policy_version == body.policy_version,
        )
    ):
        raise HTTPException(status_code=409, detail="policy_version already exists for source")
    changes = _policy_columns(body.model_dump(exclude_unset=True))
    replacement_values = {
        "name": row.name,
        "source_class": row.source_class,
        "source_type": row.source_type,
        "connector_type": row.connector_type,
        "connector_config_json": dict(row.connector_config_json),
        "enabled": row.enabled,
        "trust_score": row.trust_score,
        "trust_tier": row.trust_tier,
        "trust_rationale": row.trust_rationale,
        "license_allowed_usages_json": list(row.license_allowed_usages_json),
        "license_retention_days": row.license_retention_days,
        "license_attribution": row.license_attribution,
        "license_display_allowed": row.license_display_allowed,
        "canonical_domains_json": list(row.canonical_domains_json),
        "effective_from": changed_at,
        "effective_to": None,
    }
    replacement_values.update(changes)
    _validate_policy_domains(
        row.connector_type, cast(list[str], replacement_values["canonical_domains_json"])
    )
    requested_effective_to = cast(datetime | None, replacement_values["effective_to"])
    if requested_effective_to is not None and requested_effective_to <= changed_at:
        raise HTTPException(status_code=422, detail="effective_to must be after replacement time")
    replacement = SourcePolicyModel(
        source_policy_id=uuid4(),
        **replacement_values,
        created_by=principal.subject,
        updated_by=principal.subject,
    )
    await session.execute(
        update(SourcePolicyModel)
        .where(SourcePolicyModel.source_policy_id == row.source_policy_id)
        # Expiration is the only permitted change to the historical policy snapshot.
        .values(effective_to=changed_at, updated_at=row.updated_at)
    )
    session.add(replacement)
    session.add(
        AuditLogModel(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action="source_policy.expired",
            target_type="source_policy",
            target_id=str(row.source_policy_id),
            metadata_json={
                "effective_to": changed_at.isoformat(),
                "replacement_source_policy_id": str(replacement.source_policy_id),
            },
        )
    )
    session.add(
        AuditLogModel(
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            action="source_policy.replaced",
            target_type="source_policy",
            target_id=str(replacement.source_policy_id),
            metadata_json={
                "replaces_source_policy_id": str(row.source_policy_id),
                "previous_policy_version": row.policy_version,
                "new_policy_version": replacement.policy_version,
                "changed_fields": sorted(body.model_fields_set),
            },
        )
    )
    await session.commit()
    await session.refresh(replacement)
    return _policy(replacement)


@router.get("/source-connectors/runs", response_model=list[ConnectorRunResponse])
async def connector_runs(
    source_policy_id: UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(SourceConnectorRunModel)
    if source_policy_id:
        query = query.where(SourceConnectorRunModel.source_policy_id == source_policy_id)
    if status:
        query = query.where(SourceConnectorRunModel.status == status)
    rows = (
        await session.scalars(
            query.order_by(SourceConnectorRunModel.started_at.desc()).limit(limit)
        )
    ).all()
    return [_run(row) for row in rows]


@router.get("/disclosures/{disclosure_id}", response_model=DisclosureResponse)
async def disclosure_detail(
    disclosure_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    row = await session.get(DisclosureModel, disclosure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="disclosure not found")
    policy = (
        await session.get(SourcePolicyModel, row.source_policy_id) if row.source_policy_id else None
    )
    return _disclosure(row, display_allowed=bool(policy and policy.license_display_allowed))


@router.get("/disclosures/{disclosure_id}/versions", response_model=list[DisclosureResponse])
async def disclosure_versions(
    disclosure_id: UUID, session: AsyncSession = Depends(get_db_session)
) -> list[dict[str, Any]]:
    row = await session.get(DisclosureModel, disclosure_id)
    if row is None:
        raise HTTPException(status_code=404, detail="disclosure not found")
    versions = (
        await session.scalars(
            select(DisclosureModel)
            .where(
                DisclosureModel.logical_source_key == row.logical_source_key,
                DisclosureModel.source_document_key == row.source_document_key,
            )
            .order_by(DisclosureModel.document_version.desc())
        )
    ).all()
    policy_ids = {item.source_policy_id for item in versions if item.source_policy_id}
    policies = {
        item.source_policy_id: item
        for item in (
            await session.scalars(
                select(SourcePolicyModel).where(SourcePolicyModel.source_policy_id.in_(policy_ids))
            )
        ).all()
    }
    return [
        _disclosure(
            item,
            display_allowed=bool(
                item.source_policy_id
                and policies.get(item.source_policy_id)
                and policies[item.source_policy_id].license_display_allowed
            ),
        )
        for item in versions
    ]


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
async def claim_detail(
    claim_id: UUID,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = await _tenant_claim(session, claim_id, principal.tenant_id)
    return _claim(row)


@router.get(
    "/claims/{claim_id}/verification",
    response_model=list[ClaimVerificationResponse],
)
async def claim_verification(
    claim_id: UUID,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    await _tenant_claim(session, claim_id, principal.tenant_id)
    rows = (
        await session.scalars(
            select(ClaimVerificationModel)
            .where(ClaimVerificationModel.claim_id == claim_id)
            .order_by(ClaimVerificationModel.verified_at.desc())
        )
    ).all()
    result = []
    for row in rows:
        evidence = (
            await session.scalars(
                select(VerificationEvidenceModel)
                .where(VerificationEvidenceModel.verification_id == row.verification_id)
                .order_by(VerificationEvidenceModel.rank)
            )
        ).all()
        result.append({**_verification(row), "evidence": [_evidence(item) for item in evidence]})
    return result


@router.get("/alerts/{alert_id}/claims", response_model=list[ClaimResponse])
async def alert_claims(
    alert_id: UUID,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    alert = await session.get(AlertModel, alert_id)
    if alert is None or alert.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="alert not found")
    campaign = await session.get(CampaignModel, alert.campaign_id)
    if campaign is None or campaign.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="alert not found")
    rows = (
        await session.scalars(
            select(ClaimModel)
            .join(NarrativeModel, NarrativeModel.narrative_id == ClaimModel.narrative_id)
            .where(
                NarrativeModel.asset_id == campaign.asset_id,
                NarrativeModel.scope_id == campaign.scope_id,
                ClaimModel.extracted_at <= alert.last_triggered_at,
            )
            .order_by(ClaimModel.extracted_at.desc())
        )
    ).all()
    return [_claim(row) for row in rows]


@router.get("/verification/timeline", response_model=list[TimelineEvent])
async def verification_timeline(
    principal: CurrentPrincipal,
    claim_id: UUID | None = None,
    source_policy_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    disclosure_query = select(DisclosureModel)
    if source_policy_id:
        disclosure_query = disclosure_query.where(
            DisclosureModel.source_policy_id == source_policy_id
        )
    disclosures = (await session.scalars(disclosure_query.limit(limit))).all()
    for disclosure in disclosures:
        for event_type, event_time in (
            ("DISCLOSURE_PUBLISHED", disclosure.published_at),
            ("DISCLOSURE_OBSERVED", disclosure.first_observed_at),
            ("DISCLOSURE_AVAILABLE", disclosure.available_at),
        ):
            events.append(
                {
                    "event_type": event_type,
                    "event_time": event_time,
                    "data": {"disclosure_id": str(disclosure.disclosure_id)},
                }
            )
    verification_query = (
        select(ClaimVerificationModel)
        .join(ClaimModel, ClaimModel.claim_id == ClaimVerificationModel.claim_id)
        .join(NarrativeModel, NarrativeModel.narrative_id == ClaimModel.narrative_id)
        .join(
            CampaignModel,
            (CampaignModel.scope_id == NarrativeModel.scope_id)
            & (CampaignModel.asset_id == NarrativeModel.asset_id),
        )
        .where(CampaignModel.tenant_id == principal.tenant_id)
    )
    if claim_id:
        verification_query = verification_query.where(ClaimVerificationModel.claim_id == claim_id)
    for verification in (await session.scalars(verification_query.limit(limit))).all():
        events.append(
            {
                "event_type": "VERIFICATION",
                "event_time": verification.verified_at,
                "data": _verification(verification),
            }
        )
    claim_query = (
        select(ClaimModel)
        .join(NarrativeModel, NarrativeModel.narrative_id == ClaimModel.narrative_id)
        .join(
            CampaignModel,
            (CampaignModel.scope_id == NarrativeModel.scope_id)
            & (CampaignModel.asset_id == NarrativeModel.asset_id),
        )
        .where(CampaignModel.tenant_id == principal.tenant_id)
    )
    if claim_id:
        claim_query = claim_query.where(ClaimModel.claim_id == claim_id)
    for claim in (await session.scalars(claim_query.limit(limit))).all():
        events.append(
            {
                "event_type": "CLAIM_EXTRACTED",
                "event_time": claim.extracted_at,
                "data": _claim(claim),
            }
        )
    run_query = select(SourceConnectorRunModel)
    if source_policy_id:
        run_query = run_query.where(SourceConnectorRunModel.source_policy_id == source_policy_id)
    for connector_run in (await session.scalars(run_query.limit(limit))).all():
        events.append(
            {
                "event_type": "CONNECTOR_RUN",
                "event_time": connector_run.started_at,
                "data": _run(connector_run),
            }
        )
    return sorted(
        [
            item
            for item in events
            if (start is None or item["event_time"] >= start)
            and (end is None or item["event_time"] <= end)
        ],
        key=lambda item: item["event_time"],
        reverse=True,
    )[:limit]


async def _tenant_claim(session: AsyncSession, claim_id: UUID, tenant_id: str) -> ClaimModel:
    row = await session.scalar(
        select(ClaimModel)
        .join(NarrativeModel, NarrativeModel.narrative_id == ClaimModel.narrative_id)
        .join(
            CampaignModel,
            (CampaignModel.scope_id == NarrativeModel.scope_id)
            & (CampaignModel.asset_id == NarrativeModel.asset_id),
        )
        .where(
            ClaimModel.claim_id == claim_id,
            CampaignModel.tenant_id == tenant_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return row


def _policy_columns(data: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "connector_config": "connector_config_json",
        "license_allowed_usages": "license_allowed_usages_json",
        "canonical_domains": "canonical_domains_json",
    }
    return {aliases.get(key, key): value for key, value in data.items()}


def _policy(row: SourcePolicyModel) -> dict[str, Any]:
    return {
        "source_policy_id": row.source_policy_id,
        "name": row.name,
        "source_class": row.source_class,
        "source_type": row.source_type,
        "connector_type": row.connector_type,
        "connector_config": _redact_config(row.connector_config_json),
        "enabled": row.enabled,
        "trust_score": row.trust_score,
        "trust_tier": row.trust_tier,
        "trust_rationale": row.trust_rationale,
        "license_allowed_usages": row.license_allowed_usages_json,
        "license_retention_days": row.license_retention_days,
        "license_attribution": row.license_attribution,
        "license_display_allowed": row.license_display_allowed,
        "policy_version": row.policy_version,
        "canonical_domains": row.canonical_domains_json,
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _disclosure(row: DisclosureModel, *, display_allowed: bool) -> dict[str, Any]:
    return {
        column.name: (
            getattr(row, column.name) if column.name != "body" or display_allowed else None
        )
        for column in row.__table__.columns
    }


def _claim(row: ClaimModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _verification(row: ClaimVerificationModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _evidence(row: VerificationEvidenceModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _run(row: SourceConnectorRunModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _redact_config(value: dict[str, Any]) -> dict[str, Any]:
    secret_markers = ("token", "password", "secret", "api_key", "authorization")
    return {
        key: "[REDACTED]"
        if any(marker in key.lower() for marker in secret_markers)
        else _redact_config(item)
        if isinstance(item, dict)
        else item
        for key, item in value.items()
    }


def _validate_policy_domains(connector_type: str, canonical_domains: list[str]) -> None:
    if connector_type == "RSS_ATOM" and not canonical_domains:
        raise HTTPException(status_code=422, detail="RSS_ATOM policies require canonical_domains")


def _validate_policy_window(
    effective_from: datetime, effective_to: datetime | None, now: datetime
) -> None:
    if effective_from < now:
        raise HTTPException(status_code=422, detail="effective_from cannot be backdated")
    if effective_to is not None and effective_to <= effective_from:
        raise HTTPException(status_code=422, detail="effective_to must be after effective_from")
