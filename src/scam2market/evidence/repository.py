from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    AlertEvidenceModel,
    AlertModel,
    CampaignEvidenceModel,
    CampaignModel,
    ClaimModel,
    ClaimVerificationModel,
    EvidenceSnapshotModel,
    ExplanationModel,
    FeatureLineageModel,
    FeatureRevisionModel,
    FeatureWindowModel,
    GraphFeatureModel,
    GraphSnapshotModel,
    NarrativeModel,
)
from scam2market.evidence.schemas import EvidenceInput
from scam2market.evidence.service import EvidenceBuilder
from scam2market.schemas.events import CanonicalEvent


class EvidenceCaptureRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        builder: EvidenceBuilder | None = None,
    ) -> None:
        self._sessions = sessions
        self._builder = builder or EvidenceBuilder()

    async def capture_alert(self, event: CanonicalEvent) -> UUID:
        alert_id = UUID(str(event.payload["alert_id"]))
        async with self._sessions() as session, session.begin():
            alert = await session.get(AlertModel, alert_id)
            if alert is None:
                raise LookupError(f"alert {alert_id} not found")
            existing = await session.scalar(
                select(EvidenceSnapshotModel).where(
                    EvidenceSnapshotModel.alert_id == alert_id,
                    EvidenceSnapshotModel.alert_version == alert.version,
                )
            )
            if existing is not None:
                return existing.snapshot_id
            campaign = await session.get(CampaignModel, alert.campaign_id)
            if campaign is None:
                raise LookupError(f"campaign {alert.campaign_id} not found")
            evidence_event_id = str(event.payload["evidence_event_id"])
            campaign_evidence = await session.get(CampaignEvidenceModel, evidence_event_id)
            if campaign_evidence is None:
                raise LookupError(f"campaign evidence {evidence_event_id} not found")
            fusion = campaign_evidence.evidence_json
            feature, lineage = await self._feature_evidence(session, fusion)
            narrative = await self._narrative_evidence(session, campaign)
            graph = await self._graph_evidence(session, fusion)
            verifications = await self._verification_evidence(
                session, campaign, campaign_evidence.event_time
            )
            previous_chain_hash = await session.scalar(
                select(EvidenceSnapshotModel.chain_hash)
                .where(EvidenceSnapshotModel.alert_id == alert_id)
                .order_by(EvidenceSnapshotModel.alert_version.desc())
                .limit(1)
            )
            source = EvidenceInput(
                alert_id=alert.alert_id,
                campaign_id=campaign.campaign_id,
                scope_id=campaign.scope_id,
                asset_id=campaign.asset_id,
                alert_version=alert.version,
                alert_type=alert.alert_type,
                severity=alert.severity,
                stage=campaign.stage,
                evidence_cutoff=campaign_evidence.event_time,
                campaign_evidence_event_id=evidence_event_id,
                fusion=fusion,
                feature=feature,
                feature_lineage=lineage,
                narrative=narrative,
                graph=graph,
                verifications=verifications,
            )
            now = datetime.now(tz=UTC)
            snapshot, explanation = self._builder.build(
                source, previous_chain_hash=previous_chain_hash, created_at=now
            )
            session.add(
                EvidenceSnapshotModel(
                    snapshot_id=snapshot.snapshot_id,
                    alert_id=snapshot.alert_id,
                    campaign_id=snapshot.campaign_id,
                    scope_id=snapshot.scope_id,
                    asset_id=snapshot.asset_id,
                    alert_version=snapshot.alert_version,
                    evidence_cutoff=snapshot.evidence_cutoff,
                    schema_version=snapshot.schema_version,
                    content_json=snapshot.content,
                    content_hash=snapshot.content_hash,
                    previous_chain_hash=snapshot.previous_chain_hash,
                    chain_hash=snapshot.chain_hash,
                    completeness_score=snapshot.completeness_score,
                    completeness_json=snapshot.completeness,
                    created_at=snapshot.created_at,
                )
            )
            await session.flush()
            session.add_all(
                [
                    AlertEvidenceModel(
                        snapshot_id=snapshot.snapshot_id,
                        alert_id=snapshot.alert_id,
                        evidence_type=reference.evidence_type,
                        evidence_id=reference.evidence_id,
                        event_time=reference.event_time,
                        digest=reference.digest,
                        metadata_json=reference.metadata,
                    )
                    for reference in snapshot.references
                ]
            )
            session.add(
                ExplanationModel(
                    explanation_id=explanation.explanation_id,
                    snapshot_id=explanation.snapshot_id,
                    template_version=explanation.template_version,
                    summary=explanation.summary,
                    triggered_rules_json=explanation.triggered_rules,
                    contributors_json=explanation.contributors,
                    context_json=explanation.context,
                    llm_summary=explanation.llm_summary,
                    llm_status=explanation.llm_status,
                    generated_at=explanation.generated_at,
                )
            )
            return snapshot.snapshot_id

    @staticmethod
    async def _feature_evidence(
        session: AsyncSession, fusion: dict[str, object]
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        raw_window_id = fusion.get("feature_window_id")
        if raw_window_id is None:
            return None, None
        window = await session.get(FeatureWindowModel, UUID(str(raw_window_id)))
        if window is None:
            return None, None
        revision_number = int(str(fusion.get("feature_revision", window.current_revision)))
        revision = await session.get(
            FeatureRevisionModel, (window.feature_window_id, revision_number)
        )
        if revision is None:
            return None, None
        lineage = await session.get(FeatureLineageModel, revision.lineage_id)
        feature = {
            "feature_window_id": str(window.feature_window_id),
            "revision": revision.revision,
            "window_start": window.window_start,
            "window_end": window.window_end,
            "feature_schema_version": window.feature_schema_version,
            "feature_schema_hash": revision.feature_schema_hash,
            "is_final": revision.is_final,
            "features": revision.features_json,
        }
        lineage_payload: dict[str, object] | None = (
            {
                "lineage_id": str(lineage.lineage_id),
                "source_event_ids": lineage.source_event_ids_json,
                "source_event_min_time": lineage.source_event_min_time,
                "source_event_max_time": lineage.source_event_max_time,
                "source_count": lineage.source_count,
                "source_hash": lineage.source_hash,
            }
            if lineage is not None
            else None
        )
        return feature, lineage_payload

    @staticmethod
    async def _narrative_evidence(
        session: AsyncSession, campaign: CampaignModel
    ) -> dict[str, object] | None:
        if campaign.dominant_narrative_id is None:
            return None
        narrative = await session.get(NarrativeModel, campaign.dominant_narrative_id)
        if narrative is None:
            return None
        return {
            "narrative_id": str(narrative.narrative_id),
            "revision_id": str(narrative.current_revision_id),
            "revision": narrative.current_revision,
            "label": narrative.label,
            "summary": narrative.summary,
            "post_count": narrative.post_count,
            "unique_author_count": narrative.unique_author_count,
            "member_hash": narrative.member_hash,
        }

    @staticmethod
    async def _graph_evidence(
        session: AsyncSession, fusion: dict[str, object]
    ) -> dict[str, object] | None:
        inputs = fusion.get("input_snapshot_ids")
        if not isinstance(inputs, dict) or not inputs.get("graph_snapshot_id"):
            return None
        graph_id = UUID(str(inputs["graph_snapshot_id"]))
        row = (
            await session.execute(
                select(GraphSnapshotModel, GraphFeatureModel)
                .outerjoin(
                    GraphFeatureModel,
                    GraphFeatureModel.graph_snapshot_id == GraphSnapshotModel.graph_snapshot_id,
                )
                .where(GraphSnapshotModel.graph_snapshot_id == graph_id)
            )
        ).first()
        if row is None:
            return None
        snapshot, features = row
        return {
            "graph_snapshot_id": str(snapshot.graph_snapshot_id),
            "cutoff_event_time": snapshot.cutoff_event_time,
            "source_lineage_hash": snapshot.source_lineage_hash,
            "projection_version": snapshot.projection_version,
            "projection_status": snapshot.projection_status,
            "features": features.features_json if features is not None else None,
            "graph_score": features.graph_score if features is not None else None,
        }

    @staticmethod
    async def _verification_evidence(
        session: AsyncSession, campaign: CampaignModel, evidence_cutoff: datetime
    ) -> list[dict[str, object]]:
        if campaign.dominant_narrative_id is None:
            return []
        rows = (
            await session.execute(
                select(ClaimVerificationModel, ClaimModel)
                .join(ClaimModel, ClaimModel.claim_id == ClaimVerificationModel.claim_id)
                .where(
                    ClaimModel.narrative_id == campaign.dominant_narrative_id,
                    ClaimVerificationModel.alert_time <= evidence_cutoff,
                )
                .order_by(ClaimVerificationModel.verified_at.desc())
            )
        ).all()
        return [
            {
                "verification_id": str(verification.verification_id),
                "claim_id": str(claim.claim_id),
                "claim_text": claim.claim_text,
                "result": verification.result,
                "claim_risk": verification.claim_risk,
                "legitimate_event_score": verification.legitimate_event_score,
                "evidence_document_ids": verification.evidence_document_ids_json,
                "retrieval_metadata": verification.retrieval_metadata_json,
                "deterministic_reason": verification.deterministic_reason,
                "verifier_version": verification.verifier_version,
                "source_policy_version": verification.source_policy_version,
                "retrospective_only": verification.retrospective_only,
            }
            for verification, claim in rows
        ]
