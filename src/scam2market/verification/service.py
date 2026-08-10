import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from scam2market.narratives.embeddings import EmbeddingProvider, VectorIndex
from scam2market.narratives.schemas import NarrativeCluster
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata
from scam2market.verification.repository import VerificationRepository
from scam2market.verification.schemas import (
    Claim,
    ClaimVerification,
    DisclosureCandidate,
    DisclosureChunk,
    DisclosureDocument,
    VerificationResult,
    VerificationSummary,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CLAIM_BOUNDARY = re.compile(r"(?:[;]\s*|\s+(?:and|but|while)\s+)", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]+")
_NEGATIONS = {"no", "not", "never", "denies", "denied", "false", "without"}
_STOPWORDS = {"about", "after", "from", "have", "that", "this", "with", "will"}


class VerificationExplainer(Protocol):
    async def explain(
        self, claim: Claim, result: VerificationResult, evidence: list[DisclosureCandidate]
    ) -> str: ...


class DisclosureIngestionService:
    def __init__(
        self,
        *,
        repository: VerificationRepository,
        embedding: EmbeddingProvider,
        vector_index: VectorIndex,
        chunk_characters: int = 1200,
    ) -> None:
        self._repository = repository
        self._embedding = embedding
        self._index = vector_index
        self._chunk_characters = chunk_characters

    async def ingest(self, document: DisclosureDocument) -> bool:
        document = document.model_copy(
            update={
                "first_observed_at": document.first_observed_at or document.retrieved_at,
                "ingested_at": document.ingested_at or document.retrieved_at,
            }
        )
        assert document.first_observed_at is not None
        assert document.ingested_at is not None
        chunks = self._chunks(document)
        persisted = await self._repository.persist_disclosure(document, chunks)
        if not persisted:
            return False
        for chunk in chunks:
            vector = await self._embedding.embed(chunk.text)
            try:
                await self._index.upsert(
                    str(chunk.chunk_id),
                    vector,
                    {
                        **chunk.metadata,
                        "chunk_id": str(chunk.chunk_id),
                        "disclosure_id": str(document.disclosure_id),
                        "asset_id": document.asset_id,
                        "published_at": document.published_at.isoformat(),
                        "first_observed_at": document.first_observed_at.isoformat(),
                        "document_version": document.document_version,
                        "source_policy_version": document.source_policy_version,
                        "source": document.source,
                    },
                )
            except Exception:
                # PostgreSQL is authoritative; a Qdrant outage is retriable enrichment debt.
                continue
        return True

    def _chunks(self, document: DisclosureDocument) -> list[DisclosureChunk]:
        paragraphs = [part.strip() for part in document.body.splitlines() if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [document.body.strip()]:
            if current and len(current) + len(paragraph) + 1 > self._chunk_characters:
                chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return [
            DisclosureChunk(
                chunk_id=uuid5(NAMESPACE_URL, f"disclosure-chunk:{document.disclosure_id}:{index}"),
                disclosure_id=document.disclosure_id,
                chunk_index=index,
                text=text,
                token_count=len(_TOKEN.findall(text)),
                embedding_version=self._embedding.version,
                metadata={
                    "source_document_id": document.source_document_id,
                    "title": document.title,
                },
            )
            for index, text in enumerate(chunks)
        ]


class DeterministicClaimExtractor:
    version = "atomic-claim-extractor-v2"

    def extract(self, narrative: NarrativeCluster, extracted_at: datetime) -> list[Claim]:
        candidates = [
            part.strip(" ,")
            for sentence in _SENTENCE.split(narrative.summary)
            for part in _CLAIM_BOUNDARY.split(sentence)
            if len(_TOKEN.findall(part)) >= 3
        ]
        if not candidates and narrative.summary.strip():
            candidates = [narrative.summary.strip()]
        claims: list[Claim] = []
        seen: set[str] = set()
        for text in candidates[:5]:
            canonical = _canonical_claim(narrative.asset_id, text)
            claim_hash = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if claim_hash in seen:
                continue
            seen.add(claim_hash)
            claims.append(
                Claim(
                    claim_id=uuid5(NAMESPACE_URL, f"claim:{narrative.narrative_id}:{claim_hash}"),
                    narrative_id=narrative.narrative_id,
                    asset_id=narrative.asset_id,
                    claim_text=text,
                    claim_type=str(canonical["claim_type"]),
                    canonical_payload=canonical,
                    claim_hash=claim_hash,
                    extracted_at=extracted_at,
                    extractor_version=self.version,
                )
            )
        return claims


class TimeBoundedClaimVerifier:
    version = "availability-bounded-verifier-v2"
    source_policy_version = "official-sources-v1"

    def __init__(
        self,
        repository: VerificationRepository,
        explainer: VerificationExplainer | None = None,
        support_threshold: float = 0.34,
        lookback_days: int = 30,
        future_days: int = 7,
    ) -> None:
        self._repository = repository
        self._explainer = explainer
        self._threshold = support_threshold
        self._lookback_days = lookback_days
        self._future_days = future_days

    async def verify(self, claim: Claim, alert_time: datetime) -> ClaimVerification:
        candidates = await self._repository.candidates(
            asset_id=claim.asset_id,
            alert_time=alert_time,
            lookback_days=self._lookback_days,
            future_days=self._future_days,
        )
        scored = [(candidate, _structured_similarity(claim, candidate)) for candidate in candidates]
        matching = [
            (candidate, score)
            for candidate, score in scored
            if score * candidate.reliability >= self._threshold
        ]
        before = [item for item in matching if item[0].first_observed_at <= alert_time]
        future = [item for item in matching if item[0].first_observed_at > alert_time]
        conflict = [
            item for item in before if _is_negated(claim.claim_text) != _is_negated(item[0].text)
        ]
        if conflict:
            result = VerificationResult.conflicting
            risk, legitimate = 1.0, 0.0
            evidence = conflict
            reason = "a time-valid source materially conflicts with the extracted claim"
        elif before:
            result = VerificationResult.supported_before_alert
            risk, legitimate = 0.15, max(item[0].reliability for item in before)
            evidence = before
            reason = "supporting disclosure existed at or before the alert cutoff"
        elif future:
            result = VerificationResult.supported_after_alert
            risk, legitimate = 0.75, 0.0
            evidence = future
            reason = "support appeared only after the alert cutoff and was not used retrospectively"
        elif candidates:
            result = VerificationResult.unsupported
            risk, legitimate = 0.90, 0.0
            evidence = []
            reason = "retrieved time-bounded sources did not support the claim"
        else:
            result = VerificationResult.unknown
            risk, legitimate = 0.50, 0.0
            evidence = []
            reason = "no eligible disclosure evidence was available around the alert cutoff"

        explanation = None
        if self._explainer is not None:
            try:
                explanation = await self._explainer.explain(
                    claim, result, [item[0] for item in evidence]
                )
            except Exception:
                explanation = None
        verified_at = datetime.now(tz=UTC)
        return ClaimVerification(
            verification_id=uuid5(
                NAMESPACE_URL,
                f"verification:{claim.claim_id}:{alert_time.isoformat()}:{self.version}",
            ),
            claim_id=claim.claim_id,
            alert_time=alert_time,
            result=result,
            claim_risk=risk,
            legitimate_event_score=legitimate,
            evidence_document_ids=sorted(
                {str(candidate.disclosure_id) for candidate, _ in evidence}
            ),
            retrieval_metadata={
                "alert_cutoff": alert_time.isoformat(),
                "temporal_filter": (
                    "first_observed_at <= alert_time for contemporaneous support"
                ),
                "source_policy_version": self.source_policy_version,
                "candidate_count": len(candidates),
                "matches": [
                    {
                        "document_id": str(candidate.disclosure_id),
                        "source_document_id": candidate.source_document_id,
                        "published_at": candidate.published_at.isoformat(),
                        "first_observed_at": candidate.first_observed_at.isoformat(),
                        "similarity": round(score, 6),
                        "is_future": candidate.first_observed_at > alert_time,
                    }
                    for candidate, score in sorted(
                        matching, key=lambda item: (-item[1], str(item[0].chunk_id))
                    )
                ],
            },
            deterministic_reason=reason,
            llm_explanation=explanation,
            verifier_version=self.version,
            source_policy_version=self.source_policy_version,
            retrospective_only=result == VerificationResult.supported_after_alert,
            verified_at=verified_at,
        )


class NarrativeVerificationService:
    def __init__(
        self,
        repository: VerificationRepository,
        verifier: TimeBoundedClaimVerifier,
        extractor: DeterministicClaimExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._verifier = verifier
        self._extractor = extractor or DeterministicClaimExtractor()

    async def process(self, event: CanonicalEvent) -> VerificationSummary:
        if event.event_type != EventType.narrative_clustered:
            raise ValueError("verification requires a narrative event")
        narrative = NarrativeCluster.model_validate(event.payload["narrative"])
        claims = self._extractor.extract(narrative, event.event_time)
        verifications = [await self._verifier.verify(claim, event.event_time) for claim in claims]
        if not verifications:
            raise ValueError("narrative did not contain a verifiable claim")
        result = _aggregate_result(verifications)
        verification_snapshot_id = uuid5(
            NAMESPACE_URL,
            f"verification-snapshot:{narrative.narrative_revision_id}:"
            f"{event.event_time.isoformat()}:{self._verifier.version}",
        )
        summary = VerificationSummary(
            verification_snapshot_id=verification_snapshot_id,
            narrative_id=narrative.narrative_id,
            alert_time=event.event_time,
            result=result,
            claim_risk=max(item.claim_risk for item in verifications),
            legitimate_event_score=max(item.legitimate_event_score for item in verifications),
            claims=claims,
            verifications=verifications,
        )
        output = CanonicalEvent(
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"claim-summary:{verification_snapshot_id}",
                )
            ),
            event_type=EventType.claim_verification_completed,
            schema_version=1,
            source=self._verifier.version,
            source_event_id=f"{narrative.narrative_id}:{event.event_time.isoformat()}",
            asset_id=narrative.asset_id,
            event_time=event.event_time,
            ingested_at=datetime.now(tz=UTC),
            processed_at=datetime.now(tz=UTC),
            partition_key=narrative.asset_id,
            replay=ReplayMetadata(
                is_replay=narrative.scope_id != "LIVE",
                replay_session_id=(narrative.scope_id if narrative.scope_id != "LIVE" else None),
            ),
            payload={
                **summary.model_dump(mode="json"),
                "feature_snapshot": event.payload["feature_snapshot"],
                "graph_score": event.payload["graph_features"].get("graph_score"),
                "graph_snapshot_id": event.payload.get("graph_snapshot_id"),
            },
        )
        await self._repository.persist_verifications(claims, verifications, output)
        return summary


def disclosure_from_event(event: CanonicalEvent) -> DisclosureDocument:
    payload = dict(event.payload)
    body = str(payload.get("body") or payload.get("text") or "")
    content_hash = str(payload.get("content_hash") or hashlib.sha256(body.encode()).hexdigest())
    return DisclosureDocument(
        disclosure_id=UUID(
            str(
                payload.get("disclosure_id")
                or uuid5(NAMESPACE_URL, f"disclosure:{event.source}:{event.source_event_id}")
            )
        ),
        source=event.source,
        source_document_id=str(payload.get("source_document_id") or event.source_event_id),
        asset_id=event.asset_id,
        title=str(payload.get("title") or "Untitled disclosure"),
        body=body,
        url=(str(payload["url"]) if payload.get("url") else None),
        published_at=datetime.fromisoformat(str(payload["published_at"]))
        if payload.get("published_at")
        else event.event_time,
        retrieved_at=event.ingested_at,
        first_observed_at=(
            datetime.fromisoformat(str(payload["first_observed_at"]))
            if payload.get("first_observed_at")
            else event.ingested_at
        ),
        ingested_at=event.processed_at or event.ingested_at,
        document_version=int(payload.get("document_version", 1)),
        supersedes_disclosure_id=(
            UUID(str(payload["supersedes_disclosure_id"]))
            if payload.get("supersedes_disclosure_id")
            else None
        ),
        source_policy_version=str(payload.get("source_policy_version", "official-sources-v1")),
        reliability=float(payload.get("reliability", 1.0)),
        content_hash=content_hash,
    )


def _similarity(left: str, right: str) -> float:
    left_tokens = {token for token in _TOKEN.findall(left.lower()) if token not in _STOPWORDS}
    right_tokens = {token for token in _TOKEN.findall(right.lower()) if token not in _STOPWORDS}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _canonical_claim(asset_id: str, text: str) -> dict[str, object]:
    tokens = _TOKEN.findall(text.lower())
    lowered = " ".join(tokens)
    token_set = set(tokens)
    if "contract" in token_set or "award" in token_set:
        claim_type = "CONTRACT_AWARD"
    elif "promoter" in token_set and {"buy", "bought", "purchase"} & token_set:
        claim_type = "INSIDER_PURCHASE"
    elif "earning" in lowered or "results" in token_set:
        claim_type = "EARNINGS_FORECAST"
    elif "listing" in token_set:
        claim_type = "EXCHANGE_LISTING"
    elif "partnership" in token_set:
        claim_type = "PARTNERSHIP"
    else:
        claim_type = "OTHER"
    return {
        "subject": asset_id.upper(),
        "claim_type": claim_type,
        "polarity": "NEGATIVE" if _is_negated(text) else "POSITIVE",
        "amounts": re.findall(r"\b\d+(?:\.\d+)?\b", lowered),
        "content_tokens": sorted(
            token for token in tokens if token not in _STOPWORDS and token not in _NEGATIONS
        ),
    }


def _structured_similarity(claim: Claim, candidate: DisclosureCandidate) -> float:
    evidence_text = f"{candidate.title} {candidate.text}"
    lexical = _similarity(claim.claim_text, evidence_text)
    evidence_claim = _canonical_claim(claim.asset_id, evidence_text)
    type_match = float(evidence_claim["claim_type"] == claim.claim_type)
    polarity_match = float(
        evidence_claim["polarity"] == claim.canonical_payload.get("polarity")
    )
    claim_amounts = _string_set(claim.canonical_payload.get("amounts"))
    evidence_amounts = _string_set(evidence_claim.get("amounts"))
    amount_match = 1.0 if not claim_amounts else float(bool(claim_amounts & evidence_amounts))
    return 0.60 * lexical + 0.20 * type_match + 0.10 * polarity_match + 0.10 * amount_match


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _is_negated(text: str) -> bool:
    return bool(set(_TOKEN.findall(text.lower())) & _NEGATIONS)


def _aggregate_result(verifications: list[ClaimVerification]) -> VerificationResult:
    precedence = {
        VerificationResult.conflicting: 5,
        VerificationResult.unsupported: 4,
        VerificationResult.supported_after_alert: 3,
        VerificationResult.unknown: 2,
        VerificationResult.supported_before_alert: 1,
    }
    return max((item.result for item in verifications), key=precedence.__getitem__)
