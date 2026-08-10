from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    ClaimModel,
    ClaimVerificationModel,
    DisclosureChunkModel,
    DisclosureModel,
    EventOutboxModel,
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

    async def candidates(
        self,
        *,
        asset_id: str,
        alert_time: datetime,
        lookback_days: int = 30,
        future_days: int = 7,
    ) -> list[DisclosureCandidate]: ...

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
            existing = await session.scalar(
                select(DisclosureModel).where(
                    DisclosureModel.source == document.source,
                    DisclosureModel.source_document_id == document.source_document_id,
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
            rows = (
                await session.execute(
                    select(DisclosureChunkModel, DisclosureModel)
                    .join(
                        DisclosureModel,
                        DisclosureModel.disclosure_id == DisclosureChunkModel.disclosure_id,
                    )
                    .where(
                        or_(
                            DisclosureModel.asset_id == asset_id,
                            DisclosureModel.asset_id.is_(None),
                        ),
                        DisclosureModel.published_at >= earliest,
                        DisclosureModel.published_at <= latest,
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
                document_version=document.document_version,
                source_policy_version=document.source_policy_version,
                reliability=document.reliability,
            )
            for chunk, document in rows
        ]

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

    async def persist_disclosure(
        self, document: DisclosureDocument, chunks: list[DisclosureChunk]
    ) -> bool:
        key = f"{document.source}:{document.source_document_id}:{document.document_version}"
        if key in self.documents:
            return False
        self.documents[key] = (document, chunks)
        return True

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
        results: list[DisclosureCandidate] = []
        for document, chunks in self.documents.values():
            if document.asset_id not in {None, asset_id}:
                continue
            if not earliest <= document.published_at <= latest:
                continue
            first_observed_at = document.first_observed_at or document.retrieved_at
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
                    document_version=document.document_version,
                    source_policy_version=document.source_policy_version,
                    reliability=document.reliability,
                )
                for chunk in chunks
            )
        return sorted(results, key=lambda item: (item.published_at, str(item.chunk_id)))

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
