from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    ClaimModel,
    ClaimVerificationModel,
    DisclosureChunkModel,
    DisclosureModel,
    EventOutboxModel,
    SourceConnectorRunModel,
    SourcePolicyModel,
    VerificationEvidenceModel,
)
from scam2market.schemas.events import CanonicalEvent
from scam2market.verification.schemas import (
    Claim,
    ClaimVerification,
    DisclosureCandidate,
    DisclosureChunk,
    DisclosureDocument,
)


class VerificationRepository(Protocol):
    async def persist_disclosure(
        self, document: DisclosureDocument, chunks: list[DisclosureChunk]
    ) -> bool: ...

    async def persist_versioned_disclosure(
        self,
        document: DisclosureDocument,
        chunks_for: Callable[[DisclosureDocument], list[DisclosureChunk]],
        *,
        preserve_timestamps: bool,
    ) -> DisclosureDocument | None: ...

    async def candidates(
        self,
        *,
        asset_id: str,
        alert_time: datetime,
        lookback_days: int = 30,
        future_days: int = 7,
    ) -> list[DisclosureCandidate]: ...

    async def source_coverage(self, asset_id: str, alert_time: datetime) -> dict[str, object]: ...

    async def persist_verifications(
        self,
        claims: list[Claim],
        verifications: list[ClaimVerification],
        event: CanonicalEvent,
    ) -> bool: ...


class SqlVerificationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist_disclosure(
        self, document: DisclosureDocument, chunks: list[DisclosureChunk]
    ) -> bool:
        async with self._sessions() as session, session.begin():
            logical_key = document.logical_source_key or str(
                document.source_policy_id or document.source
            )
            document_key = document.source_document_key or document.source_document_id
            existing = await session.scalar(
                select(DisclosureModel).where(
                    DisclosureModel.logical_source_key == logical_key,
                    DisclosureModel.source_document_key == document_key,
                    DisclosureModel.document_version == document.document_version,
                )
            )
            if existing is not None:
                return False
            if document.first_observed_at is None or document.ingested_at is None:
                raise ValueError("disclosure availability timestamps must be normalized")
            session.add(
                DisclosureModel(
                    disclosure_id=document.disclosure_id,
                    source=document.source,
                    source_document_id=document.source_document_id,
                    asset_id=document.asset_id,
                    title=document.title,
                    body=document.body,
                    url=document.url,
                    published_at=document.published_at,
                    retrieved_at=document.retrieved_at,
                    first_observed_at=document.first_observed_at,
                    ingested_at=document.ingested_at,
                    document_version=document.document_version,
                    supersedes_disclosure_id=document.supersedes_disclosure_id,
                    source_policy_version=document.source_policy_version,
                    reliability=document.reliability,
                    content_hash=document.content_hash,
                    source_policy_id=document.source_policy_id,
                    connector_run_id=document.connector_run_id,
                    source_document_key=document_key,
                    logical_source_key=logical_key,
                    version_status=document.version_status,
                    available_at=document.available_at,
                    etag=document.etag,
                    last_modified=document.last_modified,
                    signature_metadata_json=document.signature_metadata,
                )
            )
            await session.flush()
            session.add_all(
                [
                    DisclosureChunkModel(
                        chunk_id=chunk.chunk_id,
                        disclosure_id=chunk.disclosure_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        embedding_version=chunk.embedding_version,
                        metadata_json=chunk.metadata,
                    )
                    for chunk in chunks
                ]
            )
        return True

    async def persist_versioned_disclosure(
        self,
        document: DisclosureDocument,
        chunks_for: Callable[[DisclosureDocument], list[DisclosureChunk]],
        *,
        preserve_timestamps: bool,
    ) -> DisclosureDocument | None:
        logical_key = document.logical_source_key or str(
            document.source_policy_id or document.source
        )
        document_key = document.source_document_key or document.source_document_id
        lock_key = f"{logical_key}:{document_key}"
        async with self._sessions() as session, session.begin():
            await session.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
            )
            latest = await session.scalar(
                select(DisclosureModel)
                .where(
                    DisclosureModel.logical_source_key == logical_key,
                    DisclosureModel.source_document_key == document_key,
                )
                .order_by(DisclosureModel.document_version.desc())
                .limit(1)
            )
            if latest and latest.content_hash == document.content_hash:
                return None
            version = latest.document_version + 1 if latest else 1
            disclosure_id = uuid5(
                NAMESPACE_URL,
                f"official-disclosure:{logical_key}:{document_key}:{version}:{document.content_hash}",
            )
            if preserve_timestamps:
                first_observed_at = document.first_observed_at or document.retrieved_at
                ingested_at = document.ingested_at or document.retrieved_at
            else:
                # This is intentionally sampled in the persistence transaction, not at fetch time.
                first_observed_at = document.first_observed_at or document.retrieved_at
                ingested_at = datetime.now(tz=document.retrieved_at.tzinfo)
            prepared = document.model_copy(
                update={
                    "disclosure_id": disclosure_id,
                    "logical_source_key": logical_key,
                    "source_document_key": document_key,
                    "document_version": version,
                    "supersedes_disclosure_id": latest.disclosure_id if latest else None,
                    "version_status": "CURRENT",
                    "first_observed_at": first_observed_at,
                    "ingested_at": ingested_at,
                    "available_at": max(first_observed_at, ingested_at),
                }
            )
            chunks = chunks_for(prepared)
            if latest:
                await session.execute(
                    update(DisclosureModel)
                    .where(DisclosureModel.disclosure_id == latest.disclosure_id)
                    .values(version_status="SUPERSEDED")
                )
            self._add_disclosure(session, prepared, chunks)
        return prepared

    @staticmethod
    def _add_disclosure(
        session: AsyncSession,
        document: DisclosureDocument,
        chunks: list[DisclosureChunk],
    ) -> None:
        if document.first_observed_at is None or document.ingested_at is None:
            raise ValueError("disclosure availability timestamps must be normalized")
        session.add(
            DisclosureModel(
                disclosure_id=document.disclosure_id,
                source=document.source,
                source_document_id=document.source_document_id,
                asset_id=document.asset_id,
                title=document.title,
                body=document.body,
                url=document.url,
                published_at=document.published_at,
                retrieved_at=document.retrieved_at,
                first_observed_at=document.first_observed_at,
                ingested_at=document.ingested_at,
                document_version=document.document_version,
                supersedes_disclosure_id=document.supersedes_disclosure_id,
                source_policy_version=document.source_policy_version,
                reliability=document.reliability,
                content_hash=document.content_hash,
                source_policy_id=document.source_policy_id,
                connector_run_id=document.connector_run_id,
                source_document_key=document.source_document_key or document.source_document_id,
                logical_source_key=document.logical_source_key
                or str(document.source_policy_id or document.source),
                version_status=document.version_status,
                available_at=document.available_at,
                etag=document.etag,
                last_modified=document.last_modified,
                signature_metadata_json=document.signature_metadata,
            )
        )
        session.add_all(
            DisclosureChunkModel(
                chunk_id=chunk.chunk_id,
                disclosure_id=chunk.disclosure_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                embedding_version=chunk.embedding_version,
                metadata_json=chunk.metadata,
            )
            for chunk in chunks
        )

    async def candidates(
        self,
        *,
        asset_id: str,
        alert_time: datetime,
        lookback_days: int = 30,
        future_days: int = 7,
    ) -> list[DisclosureCandidate]:
        earliest = alert_time - timedelta(days=lookback_days)
        latest = alert_time + timedelta(days=future_days)
        async with self._sessions() as session:
            temporal_group = case((DisclosureModel.available_at <= alert_time, 0), else_=1)
            ranked = select(
                DisclosureModel.disclosure_id.label("disclosure_id"),
                DisclosureModel.available_at.label("available_at"),
                func.row_number()
                .over(
                    partition_by=(
                        DisclosureModel.logical_source_key,
                        DisclosureModel.source_document_key,
                        temporal_group,
                    ),
                    order_by=DisclosureModel.document_version.desc(),
                )
                .label("version_rank"),
            ).subquery()
            rows = (
                await session.execute(
                    select(DisclosureChunkModel, DisclosureModel, SourcePolicyModel)
                    .join(
                        DisclosureModel,
                        DisclosureModel.disclosure_id == DisclosureChunkModel.disclosure_id,
                    )
                    .join(ranked, ranked.c.disclosure_id == DisclosureModel.disclosure_id)
                    .outerjoin(
                        SourcePolicyModel,
                        SourcePolicyModel.source_policy_id == DisclosureModel.source_policy_id,
                    )
                    .where(
                        or_(
                            DisclosureModel.asset_id == asset_id,
                            DisclosureModel.asset_id.is_(None),
                        ),
                        DisclosureModel.published_at >= earliest,
                        DisclosureModel.published_at <= latest,
                        or_(ranked.c.available_at > alert_time, ranked.c.version_rank == 1),
                    )
                    .order_by(DisclosureModel.published_at, DisclosureChunkModel.chunk_index)
                    .limit(500)
                )
            ).all()
        return [
            DisclosureCandidate(
                chunk_id=chunk.chunk_id,
                disclosure_id=document.disclosure_id,
                source=document.source,
                source_document_id=document.source_document_id,
                title=document.title,
                text=chunk.text,
                published_at=document.published_at,
                first_observed_at=document.first_observed_at,
                ingested_at=document.ingested_at,
                available_at=document.available_at,
                document_version=document.document_version,
                source_policy_version=document.source_policy_version,
                reliability=document.reliability,
                source_policy_id=document.source_policy_id,
                trust_tier=policy.trust_tier if policy else "UNSPECIFIED",
                trust_rationale=policy.trust_rationale if policy else None,
                license_snapshot=(
                    {
                        "allowed_usages": policy.license_allowed_usages_json,
                        "retention_days": policy.license_retention_days,
                        "attribution": policy.license_attribution,
                        "display_allowed": policy.license_display_allowed,
                    }
                    if policy
                    else {}
                ),
            )
            for chunk, document, policy in rows
        ]

    async def source_coverage(self, asset_id: str, alert_time: datetime) -> dict[str, object]:
        async with self._sessions() as session:
            policies = (
                await session.scalars(
                    select(SourcePolicyModel).where(
                        SourcePolicyModel.enabled.is_(True),
                        SourcePolicyModel.effective_from <= alert_time,
                        or_(
                            SourcePolicyModel.effective_to.is_(None),
                            SourcePolicyModel.effective_to > alert_time,
                        ),
                        or_(
                            SourcePolicyModel.connector_config_json["asset_id"].astext.is_(None),
                            SourcePolicyModel.connector_config_json["asset_id"].astext == asset_id,
                        ),
                    )
                )
            ).all()
            degraded: list[dict[str, object]] = []
            for policy in policies:
                run = await session.scalar(
                    select(SourceConnectorRunModel)
                    .where(
                        SourceConnectorRunModel.source_policy_id == policy.source_policy_id,
                        SourceConnectorRunModel.completed_at <= alert_time,
                    )
                    .order_by(SourceConnectorRunModel.started_at.desc())
                    .limit(1)
                )
                max_staleness = run.max_staleness_seconds if run else 86400
                stale = bool(
                    run
                    and run.completed_at
                    and (alert_time - run.completed_at).total_seconds() > max_staleness
                )
                if run is None or run.status != "SUCCESS" or stale:
                    degraded.append(
                        {
                            "source_policy_id": str(policy.source_policy_id),
                            "status": "STALE" if stale else run.status if run else "NEVER_RUN",
                        }
                    )
            return {
                "expected_source_count": len(policies),
                "degraded_source_count": len(degraded),
                "degraded_sources": degraded,
                "complete": not degraded,
            }

    async def persist_verifications(
        self,
        claims: list[Claim],
        verifications: list[ClaimVerification],
        event: CanonicalEvent,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            if await session.get(ClaimVerificationModel, verifications[0].verification_id):
                return False
            for claim in claims:
                if await session.get(ClaimModel, claim.claim_id) is None:
                    session.add(
                        ClaimModel(
                            claim_id=claim.claim_id,
                            narrative_id=claim.narrative_id,
                            asset_id=claim.asset_id,
                            claim_text=claim.claim_text,
                            claim_type=claim.claim_type,
                            canonical_json=claim.canonical_payload,
                            claim_hash=claim.claim_hash,
                            extracted_at=claim.extracted_at,
                            extractor_version=claim.extractor_version,
                        )
                    )
            await session.flush()
            session.add_all(
                [
                    ClaimVerificationModel(
                        verification_id=item.verification_id,
                        claim_id=item.claim_id,
                        alert_time=item.alert_time,
                        result=item.result.value,
                        claim_risk=item.claim_risk,
                        legitimate_event_score=item.legitimate_event_score,
                        evidence_document_ids_json=item.evidence_document_ids,
                        retrieval_metadata_json=item.retrieval_metadata,
                        deterministic_reason=item.deterministic_reason,
                        llm_explanation=item.llm_explanation,
                        verifier_version=item.verifier_version,
                        source_policy_version=item.source_policy_version,
                        retrospective_only=item.retrospective_only,
                        verified_at=item.verified_at,
                    )
                    for item in verifications
                ]
            )
            await session.flush()
            session.add_all(
                VerificationEvidenceModel(
                    verification_id=item.verification_id,
                    disclosure_id=evidence.disclosure_id,
                    relation=evidence.relation.value,
                    score=evidence.score,
                    rank=evidence.rank,
                    temporal_eligible=evidence.temporal_eligible,
                    reason_codes_json=evidence.reason_codes,
                    source_policy_id_snapshot=evidence.source_policy_id,
                    source_policy_version_snapshot=evidence.source_policy_version,
                    trust_score_snapshot=evidence.trust_score,
                    trust_tier_snapshot=evidence.trust_tier,
                    license_snapshot_json=evidence.license_snapshot,
                )
                for item in verifications
                for evidence in item.evidence
            )
            session.add(
                EventOutboxModel(
                    event_id=event.event_id,
                    topic="claim.verification.v1",
                    partition_key=event.partition_key,
                    envelope_json=event.model_dump(mode="json"),
                )
            )
        return True


class InMemoryVerificationRepository:
    def __init__(self) -> None:
        self.documents: dict[str, tuple[DisclosureDocument, list[DisclosureChunk]]] = {}
        self.verifications: list[ClaimVerification] = []
        self.outbox: list[CanonicalEvent] = []
        self.coverage: dict[str, object] = {
            "expected_source_count": 0,
            "degraded_source_count": 0,
            "degraded_sources": [],
            "complete": True,
        }
        self.coverage_by_asset: dict[str | None, dict[str, object]] = {}

    async def persist_disclosure(
        self, document: DisclosureDocument, chunks: list[DisclosureChunk]
    ) -> bool:
        key = f"{document.source}:{document.source_document_id}:{document.document_version}"
        if key in self.documents:
            return False
        self.documents[key] = (document, chunks)
        return True

    async def persist_versioned_disclosure(
        self,
        document: DisclosureDocument,
        chunks_for: Callable[[DisclosureDocument], list[DisclosureChunk]],
        *,
        preserve_timestamps: bool,
    ) -> DisclosureDocument | None:
        logical_key = document.logical_source_key or str(
            document.source_policy_id or document.source
        )
        document_key = document.source_document_key or document.source_document_id
        versions = [
            item
            for item, _ in self.documents.values()
            if (item.logical_source_key or str(item.source_policy_id or item.source)) == logical_key
            and (item.source_document_key or item.source_document_id) == document_key
        ]
        latest = max(versions, key=lambda item: item.document_version, default=None)
        if latest and latest.content_hash == document.content_hash:
            return None
        version = latest.document_version + 1 if latest else 1
        if preserve_timestamps:
            first_observed_at = document.first_observed_at or document.retrieved_at
            ingested_at = document.ingested_at or document.retrieved_at
        else:
            first_observed_at = document.first_observed_at or document.retrieved_at
            ingested_at = datetime.now(tz=document.retrieved_at.tzinfo)
        prepared = document.model_copy(
            update={
                "disclosure_id": uuid5(
                    NAMESPACE_URL,
                    f"official-disclosure:{logical_key}:{document_key}:{version}:{document.content_hash}",
                ),
                "logical_source_key": logical_key,
                "source_document_key": document_key,
                "document_version": version,
                "supersedes_disclosure_id": latest.disclosure_id if latest else None,
                "first_observed_at": first_observed_at,
                "ingested_at": ingested_at,
                "available_at": max(first_observed_at, ingested_at),
            }
        )
        if latest:
            for key, (item, chunks) in list(self.documents.items()):
                if item.disclosure_id == latest.disclosure_id:
                    self.documents[key] = (
                        item.model_copy(update={"version_status": "SUPERSEDED"}),
                        chunks,
                    )
        chunks = chunks_for(prepared)
        key = f"{logical_key}:{document_key}:{version}"
        self.documents[key] = (prepared, chunks)
        return prepared

    async def candidates(
        self,
        *,
        asset_id: str,
        alert_time: datetime,
        lookback_days: int = 30,
        future_days: int = 7,
    ) -> list[DisclosureCandidate]:
        earliest = alert_time - timedelta(days=lookback_days)
        latest = alert_time + timedelta(days=future_days)
        grouped: dict[tuple[str, str], list[tuple[DisclosureDocument, list[DisclosureChunk]]]] = (
            defaultdict(list)
        )
        for document, chunks in self.documents.values():
            grouped[
                (
                    document.logical_source_key
                    or str(document.source_policy_id or document.source),
                    document.source_document_key or document.source_document_id,
                )
            ].append((document, chunks))
        selected: list[tuple[DisclosureDocument, list[DisclosureChunk]]] = []
        for versions in grouped.values():
            eligible = [
                item
                for item in versions
                if (item[0].available_at or item[0].retrieved_at) <= alert_time
            ]
            if eligible:
                selected.append(max(eligible, key=lambda item: item[0].document_version))
            selected.extend(
                item
                for item in versions
                if (item[0].available_at or item[0].retrieved_at) > alert_time
            )
        results: list[DisclosureCandidate] = []
        for document, chunks in selected:
            if document.asset_id not in {None, asset_id}:
                continue
            if not earliest <= document.published_at <= latest:
                continue
            first_observed_at = document.first_observed_at or document.retrieved_at
            ingested_at = document.ingested_at or document.retrieved_at
            available_at = document.available_at or max(first_observed_at, ingested_at)
            results.extend(
                DisclosureCandidate(
                    chunk_id=chunk.chunk_id,
                    disclosure_id=document.disclosure_id,
                    source=document.source,
                    source_document_id=document.source_document_id,
                    title=document.title,
                    text=chunk.text,
                    published_at=document.published_at,
                    first_observed_at=first_observed_at,
                    ingested_at=ingested_at,
                    available_at=available_at,
                    document_version=document.document_version,
                    source_policy_version=document.source_policy_version,
                    reliability=document.reliability,
                    source_policy_id=document.source_policy_id,
                )
                for chunk in chunks
            )
        return sorted(results, key=lambda item: (item.published_at, str(item.chunk_id)))

    async def source_coverage(self, asset_id: str, alert_time: datetime) -> dict[str, object]:
        del alert_time
        if asset_id in self.coverage_by_asset:
            return dict(self.coverage_by_asset[asset_id])
        if None in self.coverage_by_asset:
            return dict(self.coverage_by_asset[None])
        return dict(self.coverage)

    async def persist_verifications(
        self,
        claims: list[Claim],
        verifications: list[ClaimVerification],
        event: CanonicalEvent,
    ) -> bool:
        del claims
        if any(
            item.verification_id == verifications[0].verification_id for item in self.verifications
        ):
            return False
        self.verifications.extend(verifications)
        self.outbox.append(event)
        return True
