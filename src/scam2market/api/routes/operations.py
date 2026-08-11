from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.db.models import AuditLogModel, ModelDriftEventModel, PolicyProposalModel
from scam2market.db.session import get_db_session
from scam2market.security.auth import CurrentPrincipal

router = APIRouter(prefix="/operations")


class DriftEventCreate(BaseModel):
    model_family: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    drift_score: float = Field(ge=0)
    threshold: float = Field(gt=0)
    details: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class PolicyProposalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = Field(min_length=5, max_length=4000)
    details: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=5, max_length=2000)


@router.post("/model-drift", status_code=201)
async def report_model_drift(
    body: DriftEventCreate,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    state = "DRIFTED" if body.drift_score >= body.threshold else "STABLE"
    event = ModelDriftEventModel(
        tenant_id=principal.tenant_id,
        model_family=body.model_family,
        model_version=body.model_version,
        drift_score=body.drift_score,
        threshold=body.threshold,
        status=state,
        details_json=body.details,
        observed_at=body.observed_at,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _drift_response(event)


@router.get("/model-drift")
async def list_model_drift(
    principal: CurrentPrincipal,
    model_family: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(ModelDriftEventModel).where(
        ModelDriftEventModel.tenant_id == principal.tenant_id
    )
    if model_family:
        query = query.where(ModelDriftEventModel.model_family == model_family)
    rows = (
        await session.scalars(query.order_by(ModelDriftEventModel.observed_at.desc()).limit(limit))
    ).all()
    return [_drift_response(row) for row in rows]


@router.post("/policy-proposals", status_code=201)
async def create_policy_proposal(
    body: PolicyProposalCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    proposal = PolicyProposalModel(
        tenant_id=principal.tenant_id,
        name=body.name,
        description=body.description,
        details_json=body.details,
        proposed_by=actor_id,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return _proposal_response(proposal)


@router.get("/policy-proposals")
async def list_policy_proposals(
    principal: CurrentPrincipal,
    proposal_status: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(PolicyProposalModel).where(PolicyProposalModel.tenant_id == principal.tenant_id)
    if proposal_status:
        query = query.where(PolicyProposalModel.status == proposal_status.upper())
    rows = (await session.scalars(query.order_by(PolicyProposalModel.created_at.desc()))).all()
    return [_proposal_response(row) for row in rows]


@router.post("/policy-proposals/{proposal_id}/decision")
async def decide_policy_proposal(
    proposal_id: UUID,
    body: PolicyDecision,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    proposal = await session.get(PolicyProposalModel, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="policy proposal not found")
    if proposal.status != "PENDING":
        raise HTTPException(status_code=409, detail="policy proposal already reviewed")
    proposal.status = body.status
    proposal.reviewed_by = actor_id
    proposal.review_reason = body.reason
    proposal.reviewed_at = datetime.now(tz=UTC)
    session.add(
        AuditLogModel(
            tenant_id=proposal.tenant_id,
            actor_id=actor_id,
            action=f"{body.status}_POLICY_PROPOSAL",
            target_type="POLICY_PROPOSAL",
            target_id=str(proposal_id),
            reason=body.reason,
        )
    )
    await session.commit()
    return _proposal_response(proposal)


def _drift_response(row: ModelDriftEventModel) -> dict[str, Any]:
    return {
        "drift_event_id": str(row.drift_event_id),
        "model_family": row.model_family,
        "model_version": row.model_version,
        "drift_score": row.drift_score,
        "threshold": row.threshold,
        "status": row.status,
        "details": row.details_json,
        "observed_at": row.observed_at,
    }


def _proposal_response(row: PolicyProposalModel) -> dict[str, Any]:
    return {
        "proposal_id": str(row.proposal_id),
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "details": row.details_json,
        "proposed_by": row.proposed_by,
        "reviewed_by": row.reviewed_by,
        "review_reason": row.review_reason,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
    }
