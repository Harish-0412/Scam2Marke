import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from scam2market.narratives.embeddings import (
    DeterministicHashEmbedding,
    InMemoryVectorIndex,
)
from scam2market.verification.repository import InMemoryVerificationRepository
from scam2market.verification.schemas import Claim, DisclosureDocument, VerificationResult
from scam2market.verification.service import (
    DisclosureIngestionService,
    TimeBoundedClaimVerifier,
)

ALERT_TIME = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _document(document_id: str, published_at: datetime, body: str) -> DisclosureDocument:
    return DisclosureDocument(
        disclosure_id=uuid5(NAMESPACE_URL, f"disclosure:{document_id}"),
        source="official-exchange",
        source_document_id=document_id,
        asset_id="S2MUSDT",
        title="S2M exchange listing partnership",
        body=body,
        published_at=published_at,
        retrieved_at=published_at,
        reliability=1.0,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
    )


def _claim() -> Claim:
    text = "S2M exchange listing partnership announced today"
    claim_hash = hashlib.sha256(text.lower().encode()).hexdigest()
    return Claim(
        claim_id=uuid5(NAMESPACE_URL, f"claim:{claim_hash}"),
        narrative_id=uuid5(NAMESPACE_URL, "narrative:verification"),
        asset_id="S2MUSDT",
        claim_text=text,
        claim_hash=claim_hash,
        extracted_at=ALERT_TIME,
        extractor_version="claim-extractor-v1",
    )


async def _services() -> tuple[InMemoryVerificationRepository, DisclosureIngestionService]:
    repository = InMemoryVerificationRepository()
    ingestion = DisclosureIngestionService(
        repository=repository,
        embedding=DeterministicHashEmbedding(64),
        vector_index=InMemoryVectorIndex(),
    )
    return repository, ingestion


async def test_future_disclosure_does_not_justify_past_alert() -> None:
    repository, ingestion = await _services()
    future = _document(
        "future-listing",
        ALERT_TIME + timedelta(hours=2),
        "S2M exchange listing partnership announced today",
    )
    await ingestion.ingest(future)

    result = await TimeBoundedClaimVerifier(repository).verify(_claim(), ALERT_TIME)

    assert result.result == VerificationResult.supported_after_alert
    assert result.legitimate_event_score == 0
    assert result.claim_risk >= 0.7
    matches = cast(list[dict[str, object]], result.retrieval_metadata["matches"])
    assert matches[0]["is_future"] is True


async def test_supported_before_alert_reduces_claim_risk_and_includes_metadata() -> None:
    repository, ingestion = await _services()
    prior = _document(
        "prior-listing",
        ALERT_TIME - timedelta(hours=2),
        "S2M exchange listing partnership announced today",
    )
    await ingestion.ingest(prior)

    result = await TimeBoundedClaimVerifier(repository).verify(_claim(), ALERT_TIME)

    assert result.result == VerificationResult.supported_before_alert
    assert result.claim_risk < 0.2
    assert result.legitimate_event_score == 1.0
    assert result.evidence_document_ids == [str(prior.disclosure_id)]
    assert result.retrieval_metadata["alert_cutoff"] == ALERT_TIME.isoformat()


async def test_unsupported_claim_increases_risk_and_llm_failure_is_non_blocking() -> None:
    class FailingExplainer:
        async def explain(self, *_: object) -> str:
            raise RuntimeError("LLM unavailable")

    repository, ingestion = await _services()
    unrelated = _document(
        "maintenance",
        ALERT_TIME - timedelta(hours=1),
        "The exchange scheduled routine wallet maintenance for another token",
    )
    await ingestion.ingest(unrelated)

    result = await TimeBoundedClaimVerifier(repository, explainer=FailingExplainer()).verify(
        _claim(), ALERT_TIME
    )

    assert result.result == VerificationResult.unsupported
    assert result.claim_risk == 0.9
    assert result.llm_explanation is None
