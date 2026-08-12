from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.db.models import (
    AlertEvidenceModel,
    AlertModel,
    AnalystFeedbackModel,
    AuditLogModel,
    CampaignModel,
    EvidenceSnapshotModel,
    ExplanationModel,
    InvestigationEventModel,
    InvestigationModel,
)
from scam2market.db.session import get_db_session
from scam2market.evidence.schemas import (
    FeedbackAdjudication,
    FeedbackCreate,
    InvestigationCreate,
    InvestigationEventCreate,
    InvestigationStatus,
    InvestigationUpdate,
)
from scam2market.security.auth import CurrentPrincipal

router = APIRouter()


@router.get("/alerts/{alert_id}/evidence")
async def alert_evidence(
    alert_id: UUID,
    version: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    query = select(EvidenceSnapshotModel).where(EvidenceSnapshotModel.alert_id == alert_id)
    if version is not None:
        query = query.where(EvidenceSnapshotModel.alert_version == version)
    snapshot = await session.scalar(query.order_by(EvidenceSnapshotModel.alert_version.desc()))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="evidence snapshot not found")
    references = (
        await session.scalars(
            select(AlertEvidenceModel)
            .where(AlertEvidenceModel.snapshot_id == snapshot.snapshot_id)
            .order_by(AlertEvidenceModel.evidence_type, AlertEvidenceModel.evidence_id)
        )
    ).all()
    return _snapshot_response(snapshot, references, include_content=False)


@router.get("/alerts/{alert_id}/explanation")
async def alert_explanation(
    alert_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(ExplanationModel, EvidenceSnapshotModel)
            .join(
                EvidenceSnapshotModel,
                EvidenceSnapshotModel.snapshot_id == ExplanationModel.snapshot_id,
            )
            .where(EvidenceSnapshotModel.alert_id == alert_id)
            .order_by(EvidenceSnapshotModel.alert_version.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="alert explanation not found")
    explanation, snapshot = row
    return {
        "explanation_id": str(explanation.explanation_id),
        "snapshot_id": str(snapshot.snapshot_id),
        "alert_version": snapshot.alert_version,
        "template_version": explanation.template_version,
        "summary": explanation.summary,
        "triggered_rules": explanation.triggered_rules_json,
        "contributors": explanation.contributors_json,
        "context": explanation.context_json,
        "llm_summary": explanation.llm_summary,
        "llm_status": explanation.llm_status,
        "generated_at": explanation.generated_at,
    }


@router.get("/evidence/{snapshot_id}/manifest")
async def evidence_manifest(
    snapshot_id: UUID,
    request: Request,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    access_reason: Annotated[str, Header(alias="X-Access-Reason", min_length=5)],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    snapshot = await session.get(EvidenceSnapshotModel, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="evidence snapshot not found")
    references = (
        await session.scalars(
            select(AlertEvidenceModel).where(AlertEvidenceModel.snapshot_id == snapshot_id)
        )
    ).all()
    session.add(
        AuditLogModel(
            actor_id=actor_id,
            action="READ_EVIDENCE_MANIFEST",
            target_type="EVIDENCE_SNAPSHOT",
            target_id=str(snapshot_id),
            reason=access_reason,
            request_id=request.state.request_id,
            correlation_id=request.state.correlation_id,
            metadata_json={"alert_id": str(snapshot.alert_id), "scope_id": snapshot.scope_id},
        )
    )
    await session.commit()
    return _snapshot_response(snapshot, references, include_content=True)


@router.post("/investigations", status_code=201)
async def create_investigation(
    body: InvestigationCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    alert = await session.get(AlertModel, body.alert_id)
    snapshot = await session.get(EvidenceSnapshotModel, body.snapshot_id)
    if alert is None or snapshot is None or snapshot.alert_id != alert.alert_id:
        raise HTTPException(status_code=422, detail="alert and evidence snapshot do not match")
    campaign = await session.get(CampaignModel, alert.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=422, detail="alert campaign not found")
    investigation = InvestigationModel(
        tenant_id=principal.tenant_id,
        scope_id=campaign.scope_id,
        alert_id=body.alert_id,
        snapshot_id=body.snapshot_id,
        title=body.title,
        priority=body.priority.value,
        assigned_to=body.assigned_to,
        tags_json=sorted(set(body.tags)),
        sla_due_at=datetime.now(tz=UTC) + timedelta(hours=body.sla_hours),
        opened_by=actor_id,
    )
    session.add(investigation)
    await session.flush()
    session.add(
        InvestigationEventModel(
            investigation_id=investigation.investigation_id,
            event_type="OPENED",
            actor_id=actor_id,
            details_json={"priority": body.priority.value, "tags": sorted(set(body.tags))},
        )
    )
    await session.commit()
    await session.refresh(investigation)
    return _investigation_response(investigation)


@router.get("/investigations")
async def list_investigations(
    principal: CurrentPrincipal,
    scope_id: str = "LIVE",
    status: InvestigationStatus | None = None,
    assigned_to: str | None = None,
    overdue_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    query = select(InvestigationModel).where(
        InvestigationModel.tenant_id == principal.tenant_id,
        InvestigationModel.scope_id == scope_id,
    )
    if status is not None:
        query = query.where(InvestigationModel.status == status.value)
    if assigned_to is not None:
        query = query.where(InvestigationModel.assigned_to == assigned_to)
    if overdue_only:
        query = query.where(
            InvestigationModel.sla_due_at < datetime.now(tz=UTC),
            InvestigationModel.status != InvestigationStatus.closed.value,
        )
    rows = (
        await session.scalars(query.order_by(InvestigationModel.updated_at.desc()).limit(limit))
    ).all()
    return [_investigation_response(row) for row in rows]


@router.patch("/investigations/{investigation_id}")
async def update_investigation(
    investigation_id: UUID,
    body: InvestigationUpdate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    investigation = await session.scalar(
        select(InvestigationModel)
        .where(InvestigationModel.investigation_id == investigation_id)
        .with_for_update()
    )
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    if investigation.version != body.expected_version:
        raise HTTPException(status_code=409, detail="investigation version conflict")
    changes = body.model_dump(exclude_none=True, exclude={"expected_version"})
    if body.status is not None:
        investigation.status = body.status.value
        if body.status == InvestigationStatus.closed:
            investigation.closed_at = datetime.now(tz=UTC)
    if body.priority is not None:
        investigation.priority = body.priority.value
    if "assigned_to" in changes:
        investigation.assigned_to = body.assigned_to
    if body.tags is not None:
        investigation.tags_json = sorted(set(body.tags))
    if body.disposition is not None:
        investigation.disposition = body.disposition
    investigation.version += 1
    session.add(
        InvestigationEventModel(
            investigation_id=investigation_id,
            event_type="UPDATED",
            actor_id=actor_id,
            details_json=changes,
        )
    )
    await session.commit()
    await session.refresh(investigation)
    return _investigation_response(investigation)


@router.post("/investigations/{investigation_id}/events", status_code=201)
async def add_investigation_event(
    investigation_id: UUID,
    body: InvestigationEventCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if await session.get(InvestigationModel, investigation_id) is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    item = InvestigationEventModel(
        investigation_id=investigation_id,
        event_type=body.event_type.upper(),
        actor_id=actor_id,
        details_json=body.details,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {
        "investigation_event_id": str(item.investigation_event_id),
        "event_type": item.event_type,
        "actor_id": item.actor_id,
        "details": item.details_json,
        "occurred_at": item.occurred_at,
    }


@router.post("/investigations/{investigation_id}/feedback", status_code=201)
async def add_feedback(
    investigation_id: UUID,
    body: FeedbackCreate,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    investigation = await session.get(InvestigationModel, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    feedback = AnalystFeedbackModel(
        investigation_id=investigation_id,
        alert_id=investigation.alert_id,
        snapshot_id=investigation.snapshot_id,
        analyst_id=actor_id,
        label=body.label.value,
        confidence=body.confidence,
        rationale=body.rationale,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return _feedback_response(feedback)


@router.post("/feedback/{feedback_id}/adjudicate")
async def adjudicate_feedback(
    feedback_id: UUID,
    body: FeedbackAdjudication,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    feedback = await session.get(AnalystFeedbackModel, feedback_id)
    if feedback is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    if feedback.status != "PENDING":
        raise HTTPException(status_code=409, detail="feedback has already been adjudicated")
    feedback.status = "ACCEPTED" if body.accepted else "REJECTED"
    feedback.adjudicated_by = actor_id
    feedback.adjudicated_at = datetime.now(tz=UTC)
    feedback.adjudication_note = body.note
    await session.commit()
    await session.refresh(feedback)
    return _feedback_response(feedback)


def _snapshot_response(
    snapshot: EvidenceSnapshotModel,
    references: Sequence[AlertEvidenceModel],
    *,
    include_content: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "snapshot_id": str(snapshot.snapshot_id),
        "alert_id": str(snapshot.alert_id),
        "campaign_id": str(snapshot.campaign_id),
        "scope_id": snapshot.scope_id,
        "asset_id": snapshot.asset_id,
        "alert_version": snapshot.alert_version,
        "evidence_cutoff": snapshot.evidence_cutoff,
        "schema_version": snapshot.schema_version,
        "content_hash": snapshot.content_hash,
        "previous_chain_hash": snapshot.previous_chain_hash,
        "chain_hash": snapshot.chain_hash,
        "completeness_score": snapshot.completeness_score,
        "completeness": snapshot.completeness_json,
        "created_at": snapshot.created_at,
        "references": [
            {
                "type": item.evidence_type,
                "id": item.evidence_id,
                "event_time": item.event_time,
                "digest": item.digest,
                "metadata": item.metadata_json,
            }
            for item in references
        ],
    }
    if include_content:
        result["content"] = snapshot.content_json
    return result


def _investigation_response(item: InvestigationModel) -> dict[str, Any]:
    return {
        "investigation_id": str(item.investigation_id),
        "scope_id": item.scope_id,
        "alert_id": str(item.alert_id),
        "snapshot_id": str(item.snapshot_id),
        "title": item.title,
        "status": item.status,
        "priority": item.priority,
        "assigned_to": item.assigned_to,
        "tags": item.tags_json,
        "sla_due_at": item.sla_due_at,
        "sla_breached": bool(
            item.sla_due_at
            and item.sla_due_at < datetime.now(tz=UTC)
            and item.status != InvestigationStatus.closed.value
        ),
        "disposition": item.disposition,
        "version": item.version,
        "opened_by": item.opened_by,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "closed_at": item.closed_at,
    }


def _feedback_response(item: AnalystFeedbackModel) -> dict[str, Any]:
    return {
        "feedback_id": str(item.feedback_id),
        "investigation_id": str(item.investigation_id),
        "label": item.label,
        "confidence": item.confidence,
        "rationale": item.rationale,
        "status": item.status,
        "analyst_id": item.analyst_id,
        "adjudicated_by": item.adjudicated_by,
        "adjudicated_at": item.adjudicated_at,
        "adjudication_note": item.adjudication_note,
    }
