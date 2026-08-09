import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.campaigns.policy import CampaignStateMachine, max_risk
from scam2market.campaigns.schemas import (
    AlertRecord,
    AlertStatus,
    AlertTrigger,
    AlertType,
    CampaignEvidence,
    CampaignRecord,
    CampaignStage,
    CampaignStatus,
    CampaignUpdate,
)
from scam2market.db.models import (
    AlertModel,
    AlertStateHistoryModel,
    CampaignEvidenceModel,
    CampaignModel,
    CampaignStageHistoryModel,
    EventOutboxModel,
)
from scam2market.intelligence.fusion import RiskLevel
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata, TraceMetadata


class CampaignRepository(Protocol):
    async def apply(
        self, evidence: CampaignEvidence, state_machine: CampaignStateMachine
    ) -> CampaignUpdate: ...


class SqlCampaignRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        merge_gap_seconds: int = 1800,
        suppression_seconds: int = 300,
    ) -> None:
        self._sessions = sessions
        self._merge_gap = timedelta(seconds=merge_gap_seconds)
        self._suppression = timedelta(seconds=suppression_seconds)

    async def apply(
        self, evidence: CampaignEvidence, state_machine: CampaignStateMachine
    ) -> CampaignUpdate:
        emitted: list[str] = []
        alert_records: list[AlertRecord] = []
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:campaign_key, 0))"),
                {"campaign_key": f"{evidence.scope_id}:{evidence.asset_id}"},
            )
            prior = await session.get(CampaignEvidenceModel, evidence.event_id)
            if prior is not None:
                campaign = await session.get(CampaignModel, prior.campaign_id)
                if campaign is None:
                    raise RuntimeError("campaign evidence references a missing campaign")
                return CampaignUpdate(campaign=_campaign_record(campaign), duplicate_evidence=True)

            campaign = await session.scalar(
                select(CampaignModel)
                .where(
                    CampaignModel.scope_id == evidence.scope_id,
                    CampaignModel.asset_id == evidence.asset_id,
                    CampaignModel.status == CampaignStatus.active.value,
                )
                .with_for_update()
            )
            if (
                campaign is not None
                and evidence.event_time - campaign.last_evidence_at > self._merge_gap
            ):
                campaign.status = CampaignStatus.closed.value
                campaign.version += 1
                closed = _domain_event(
                    evidence,
                    EventType.campaign_closed,
                    "campaign.events.v1",
                    campaign.campaign_id,
                    {"campaign_id": str(campaign.campaign_id), "reason": "merge gap elapsed"},
                )
                _enqueue(session, "campaign.events.v1", closed)
                emitted.append(closed.event_id)
                campaign = None

            current_stage = (
                CampaignStage(campaign.stage) if campaign is not None else CampaignStage.normal
            )
            assessment = state_machine.assess(current_stage, evidence.fusion)
            is_new = campaign is None
            if is_new:
                campaign = CampaignModel(
                    campaign_id=uuid5(
                        NAMESPACE_URL,
                        f"campaign:{evidence.scope_id}:{evidence.asset_id}:{evidence.event_id}",
                    ),
                    scope_id=evidence.scope_id,
                    asset_id=evidence.asset_id,
                    stage=assessment.next_stage.value,
                    status=CampaignStatus.active.value,
                    max_severity=evidence.fusion.severity.value,
                    first_evidence_at=evidence.event_time,
                    last_evidence_at=evidence.event_time,
                    version=1,
                )
                session.add(campaign)
                await session.flush()
                session.add(
                    CampaignStageHistoryModel(
                        campaign_id=campaign.campaign_id,
                        from_stage=None,
                        to_stage=assessment.next_stage.value,
                        evidence_event_id=evidence.event_id,
                        reason=assessment.transition_reason,
                        transitioned_at=evidence.event_time,
                    )
                )
                created = _domain_event(
                    evidence,
                    EventType.campaign_created,
                    "campaign.events.v1",
                    campaign.campaign_id,
                    _campaign_payload(campaign),
                )
                _enqueue(session, "campaign.events.v1", created)
                emitted.append(created.event_id)
            else:
                assert campaign is not None
                old_stage = CampaignStage(campaign.stage)
                campaign.last_evidence_at = max(campaign.last_evidence_at, evidence.event_time)
                campaign.max_severity = max_risk(
                    RiskLevel(campaign.max_severity), evidence.fusion.severity
                ).value
                campaign.version += 1
                if assessment.next_stage != old_stage:
                    campaign.stage = assessment.next_stage.value
                    session.add(
                        CampaignStageHistoryModel(
                            campaign_id=campaign.campaign_id,
                            from_stage=old_stage.value,
                            to_stage=assessment.next_stage.value,
                            evidence_event_id=evidence.event_id,
                            reason=assessment.transition_reason,
                            transitioned_at=evidence.event_time,
                        )
                    )
                    changed = _domain_event(
                        evidence,
                        EventType.campaign_stage_changed,
                        "campaign.events.v1",
                        campaign.campaign_id,
                        {
                            **_campaign_payload(campaign),
                            "from_stage": old_stage.value,
                            "reason": assessment.transition_reason,
                        },
                    )
                    _enqueue(session, "campaign.events.v1", changed)
                    emitted.append(changed.event_id)

            assert campaign is not None
            fingerprint = _fingerprint(evidence.fusion.model_dump(mode="json"))
            session.add(
                CampaignEvidenceModel(
                    evidence_event_id=evidence.event_id,
                    campaign_id=campaign.campaign_id,
                    event_time=evidence.event_time,
                    evidence_type=EventType.model_fusion_scored.value,
                    evidence_fingerprint=fingerprint,
                    evidence_json=evidence.fusion.model_dump(mode="json"),
                )
            )
            for trigger in assessment.alerts:
                record, event = await self._upsert_alert(
                    session, campaign, evidence, trigger, fingerprint
                )
                alert_records.append(record)
                if event is not None:
                    _enqueue(session, "alerts.events.v1", event)
                    emitted.append(event.event_id)

        return CampaignUpdate(
            campaign=_campaign_record(campaign),
            alerts=alert_records,
            emitted_event_ids=emitted,
        )

    async def _upsert_alert(
        self,
        session: AsyncSession,
        campaign: CampaignModel,
        evidence: CampaignEvidence,
        trigger: AlertTrigger,
        fingerprint: str,
    ) -> tuple[AlertRecord, CanonicalEvent | None]:
        alert = await session.scalar(
            select(AlertModel)
            .where(
                AlertModel.campaign_id == campaign.campaign_id,
                AlertModel.alert_type == trigger.alert_type.value,
            )
            .with_for_update()
        )
        old_severity: str | None = None
        old_status: str | None = None
        event_type = EventType.alert_created
        if alert is None:
            alert = AlertModel(
                alert_id=uuid5(
                    NAMESPACE_URL, f"alert:{campaign.campaign_id}:{trigger.alert_type.value}"
                ),
                campaign_id=campaign.campaign_id,
                alert_type=trigger.alert_type.value,
                severity=trigger.severity.value,
                status=AlertStatus.active.value,
                first_triggered_at=evidence.event_time,
                last_triggered_at=evidence.event_time,
                last_notified_at=evidence.event_time,
                occurrence_count=1,
                evidence_fingerprint=fingerprint,
                version=1,
            )
            session.add(alert)
            await session.flush()
            suppressed = False
        else:
            old_severity = alert.severity
            old_status = alert.status
            alert.last_triggered_at = max(alert.last_triggered_at, evidence.event_time)
            alert.occurrence_count += 1
            alert.evidence_fingerprint = fingerprint
            alert.status = AlertStatus.active.value
            alert.severity = max_risk(RiskLevel(alert.severity), trigger.severity).value
            alert.version += 1
            severity_changed = alert.severity != old_severity or alert.status != old_status
            suppressed = (
                not severity_changed
                and alert.last_notified_at is not None
                and evidence.event_time - alert.last_notified_at < self._suppression
            )
            if severity_changed:
                event_type = EventType.alert_severity_changed
            else:
                event_type = EventType.alert_refreshed
            if not suppressed:
                alert.last_notified_at = evidence.event_time

        session.add(
            AlertStateHistoryModel(
                alert_id=alert.alert_id,
                evidence_event_id=evidence.event_id,
                from_severity=old_severity,
                to_severity=alert.severity,
                from_status=old_status,
                to_status=alert.status,
                suppression_reason=("COOLDOWN" if suppressed else None),
                changed_at=evidence.event_time,
            )
        )
        event = None
        if not suppressed:
            event = _domain_event(
                evidence,
                event_type,
                "alerts.events.v1",
                alert.alert_id,
                {
                    **_alert_payload(alert),
                    "scope_id": campaign.scope_id,
                    "asset_id": campaign.asset_id,
                    "stage": campaign.stage,
                    "reason": trigger.reason,
                    "evidence_event_id": evidence.event_id,
                },
            )
        return _alert_record(alert), event


class InMemoryCampaignRepository:
    def __init__(self, *, merge_gap_seconds: int = 1800, suppression_seconds: int = 300) -> None:
        self._lock = asyncio.Lock()
        self._merge_gap = timedelta(seconds=merge_gap_seconds)
        self._suppression = timedelta(seconds=suppression_seconds)
        self.campaigns: dict[tuple[str, str], CampaignRecord] = {}
        self.alerts: dict[tuple[UUID, AlertType], AlertRecord] = {}
        self.evidence_ids: set[str] = set()
        self.stage_history: list[tuple[UUID, CampaignStage, CampaignStage]] = []
        self.alert_history: list[tuple[UUID, RiskLevel, bool]] = []
        self.outbox: list[tuple[str, CanonicalEvent]] = []

    async def apply(
        self, evidence: CampaignEvidence, state_machine: CampaignStateMachine
    ) -> CampaignUpdate:
        async with self._lock:
            key = (evidence.scope_id, evidence.asset_id)
            existing = self.campaigns.get(key)
            if evidence.event_id in self.evidence_ids:
                if existing is None:
                    raise RuntimeError("duplicate evidence has no campaign")
                return CampaignUpdate(campaign=existing, duplicate_evidence=True)
            self.evidence_ids.add(evidence.event_id)
            if (
                existing is not None
                and evidence.event_time - existing.last_evidence_at > self._merge_gap
            ):
                existing = None
            current = existing.stage if existing is not None else CampaignStage.normal
            assessment = state_machine.assess(current, evidence.fusion)
            emitted: list[str] = []
            if existing is None:
                campaign = CampaignRecord(
                    campaign_id=uuid5(
                        NAMESPACE_URL,
                        f"campaign:{evidence.scope_id}:{evidence.asset_id}:{evidence.event_id}",
                    ),
                    scope_id=evidence.scope_id,
                    asset_id=evidence.asset_id,
                    stage=assessment.next_stage,
                    status=CampaignStatus.active,
                    max_severity=evidence.fusion.severity,
                    first_evidence_at=evidence.event_time,
                    last_evidence_at=evidence.event_time,
                    version=1,
                )
                event_type = EventType.campaign_created
            else:
                campaign = existing.model_copy(
                    update={
                        "stage": assessment.next_stage,
                        "max_severity": max_risk(existing.max_severity, evidence.fusion.severity),
                        "last_evidence_at": max(existing.last_evidence_at, evidence.event_time),
                        "version": existing.version + 1,
                    }
                )
                event_type = EventType.campaign_stage_changed
                if campaign.stage != existing.stage:
                    self.stage_history.append(
                        (campaign.campaign_id, existing.stage, campaign.stage)
                    )
            self.campaigns[key] = campaign
            if existing is None or campaign.stage != existing.stage:
                event = _domain_event(
                    evidence,
                    event_type,
                    "campaign.events.v1",
                    campaign.campaign_id,
                    campaign.model_dump(mode="json"),
                )
                self.outbox.append(("campaign.events.v1", event))
                emitted.append(event.event_id)

            records: list[AlertRecord] = []
            for trigger in assessment.alerts:
                alert_key = (campaign.campaign_id, trigger.alert_type)
                alert = self.alerts.get(alert_key)
                if alert is None:
                    alert = AlertRecord(
                        alert_id=uuid5(
                            NAMESPACE_URL,
                            f"alert:{campaign.campaign_id}:{trigger.alert_type.value}",
                        ),
                        campaign_id=campaign.campaign_id,
                        alert_type=trigger.alert_type,
                        severity=trigger.severity,
                        status=AlertStatus.active,
                        first_triggered_at=evidence.event_time,
                        last_triggered_at=evidence.event_time,
                        last_notified_at=evidence.event_time,
                        occurrence_count=1,
                        version=1,
                    )
                    suppressed = False
                    alert_event_type = EventType.alert_created
                else:
                    severity = max_risk(alert.severity, trigger.severity)
                    changed = severity != alert.severity or alert.status != AlertStatus.active
                    suppressed = (
                        not changed
                        and alert.last_notified_at is not None
                        and evidence.event_time - alert.last_notified_at < self._suppression
                    )
                    alert = alert.model_copy(
                        update={
                            "severity": severity,
                            "status": AlertStatus.active,
                            "last_triggered_at": max(alert.last_triggered_at, evidence.event_time),
                            "last_notified_at": (
                                alert.last_notified_at if suppressed else evidence.event_time
                            ),
                            "occurrence_count": alert.occurrence_count + 1,
                            "version": alert.version + 1,
                        }
                    )
                    alert_event_type = (
                        EventType.alert_severity_changed if changed else EventType.alert_refreshed
                    )
                self.alerts[alert_key] = alert
                self.alert_history.append((alert.alert_id, alert.severity, suppressed))
                records.append(alert)
                if not suppressed:
                    event = _domain_event(
                        evidence,
                        alert_event_type,
                        "alerts.events.v1",
                        alert.alert_id,
                        {**alert.model_dump(mode="json"), "reason": trigger.reason},
                    )
                    self.outbox.append(("alerts.events.v1", event))
                    emitted.append(event.event_id)
            return CampaignUpdate(campaign=campaign, alerts=records, emitted_event_ids=emitted)


def _domain_event(
    evidence: CampaignEvidence,
    event_type: EventType,
    topic: str,
    entity_id: UUID,
    payload: dict[str, object],
) -> CanonicalEvent:
    source_event_id = f"{entity_id}:{event_type.value}:{evidence.event_id}"
    event_id = str(uuid5(NAMESPACE_URL, f"{topic}:{source_event_id}"))
    return CanonicalEvent(
        event_id=event_id,
        event_type=event_type,
        schema_version=1,
        source="campaign-engine-v1",
        source_event_id=source_event_id,
        asset_id=evidence.asset_id,
        event_time=evidence.event_time,
        ingested_at=datetime.now(tz=UTC),
        processed_at=datetime.now(tz=UTC),
        partition_key=evidence.asset_id,
        replay=ReplayMetadata(
            is_replay=evidence.scope_id != "LIVE",
            replay_session_id=(evidence.scope_id if evidence.scope_id != "LIVE" else None),
        ),
        trace=TraceMetadata(
            correlation_id=evidence.correlation_id,
            causation_id=evidence.event_id,
        ),
        payload=payload,
    )


def _enqueue(session: AsyncSession, topic: str, event: CanonicalEvent) -> None:
    session.add(
        EventOutboxModel(
            event_id=event.event_id,
            topic=topic,
            partition_key=event.partition_key,
            envelope_json=event.model_dump(mode="json"),
        )
    )


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _campaign_payload(campaign: CampaignModel) -> dict[str, object]:
    return {
        "campaign_id": str(campaign.campaign_id),
        "scope_id": campaign.scope_id,
        "asset_id": campaign.asset_id,
        "stage": campaign.stage,
        "status": campaign.status,
        "max_severity": campaign.max_severity,
        "first_evidence_at": campaign.first_evidence_at.isoformat(),
        "last_evidence_at": campaign.last_evidence_at.isoformat(),
        "version": campaign.version,
    }


def _alert_payload(alert: AlertModel) -> dict[str, object]:
    return {
        "alert_id": str(alert.alert_id),
        "campaign_id": str(alert.campaign_id),
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "status": alert.status,
        "first_triggered_at": alert.first_triggered_at.isoformat(),
        "last_triggered_at": alert.last_triggered_at.isoformat(),
        "last_notified_at": (
            alert.last_notified_at.isoformat() if alert.last_notified_at else None
        ),
        "occurrence_count": alert.occurrence_count,
        "version": alert.version,
    }


def _campaign_record(row: CampaignModel) -> CampaignRecord:
    return CampaignRecord.model_validate(_campaign_payload(row))


def _alert_record(row: AlertModel) -> AlertRecord:
    return AlertRecord.model_validate(_alert_payload(row))
