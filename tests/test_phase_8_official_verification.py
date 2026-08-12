import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
from fastapi import HTTPException

from scam2market.api.routes.verification import _validate_policy_window
from scam2market.narratives.embeddings import DeterministicHashEmbedding, InMemoryVectorIndex
from scam2market.verification.connectors import ConnectorError, build_connector
from scam2market.verification.repository import InMemoryVerificationRepository
from scam2market.verification.schemas import (
    Claim,
    DisclosureDocument,
    EvidenceRelation,
    VerificationResult,
)
from scam2market.verification.service import DisclosureIngestionService, TimeBoundedClaimVerifier

ALERT = datetime(2026, 8, 12, 12, tzinfo=UTC)
POLICY_ID = uuid4()


def _public_dns(host: str) -> list[str]:
    del host
    return ["93.184.216.34"]


def _client(response: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))


def _connector(kind: str, config: dict[str, object], response: httpx.Response) -> Any:
    domains = {
        "RSS_ATOM": ["official.example"],
        "GITHUB_RELEASES": ["api.github.com", "github.com"],
        "SEC_EDGAR": ["data.sec.gov", "www.sec.gov"],
    }[kind]
    return build_connector(
        kind,
        policy_id=POLICY_ID,
        source_name="official-test",
        policy_version="v1",
        trust_score=0.95,
        config=config,
        canonical_domains=domains,
        client=_client(response),
        resolve_host=_public_dns,
    )


async def test_rss_atom_parsing_and_version_identity() -> None:
    response = httpx.Response(
        200,
        content=b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>release-1</id>
        <title>Listing</title><updated>2026-08-12T10:00:00Z</updated>
        <link href="https://official.example/release-1"/><content>S2M listing announced</content>
        </entry></feed>""",
        headers={"etag": '"v1"'},
        request=httpx.Request("GET", "https://official.example/feed"),
    )
    connector = _connector("RSS_ATOM", {"url": "https://official.example/feed"}, response)
    first = (await connector.fetch())[0]
    second = (await connector.fetch())[0]

    assert first.source_document_key == "release-1"
    assert first.disclosure_id == second.disclosure_id
    assert first.etag == '"v1"'


async def test_github_release_and_sec_recent_filing_parsing() -> None:
    github_response = httpx.Response(
        200,
        json=[
            {
                "id": 123,
                "tag_name": "v1.2.3",
                "name": "Release 1.2.3",
                "body": "Security release",
                "published_at": "2026-08-12T10:00:00Z",
                "html_url": "https://github.com/acme/project/releases/123",
            }
        ],
        request=httpx.Request("GET", "https://api.github.com/repos/acme/project/releases"),
    )
    github = _connector("GITHUB_RELEASES", {"repository": "acme/project"}, github_response)
    assert (await github.fetch())[0].source_document_id == "123"

    sec_response = httpx.Response(
        200,
        json={
            "name": "Acme Corp",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000123456-26-000001"],
                    "form": ["8-K"],
                    "filingDate": ["2026-08-12"],
                    "primaryDocument": ["acme-8k.htm"],
                    "primaryDocDescription": ["Current report"],
                }
            },
        },
        request=httpx.Request("GET", "https://data.sec.gov/submissions/CIK0000123456.json"),
    )
    sec = _connector(
        "SEC_EDGAR",
        {
            "cik": "123456",
            "user_agent": "Compliance compliance@example.com",
            "fetch_filing_body": False,
        },
        sec_response,
    )
    filing = (await sec.fetch())[0]
    assert filing.source_document_id == "0000123456-26-000001"
    assert "8-K" in filing.title


async def test_sec_connector_fetches_filing_body() -> None:
    submissions_url = "https://data.sec.gov/submissions/CIK0000123456.json"
    filing_url = "https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/acme-8k.htm"

    def respond(request: httpx.Request) -> httpx.Response:
        if str(request.url) == submissions_url:
            return httpx.Response(
                200,
                json={
                    "name": "Acme Corp",
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000123456-26-000001"],
                            "form": ["8-K"],
                            "filingDate": ["2026-08-12"],
                            "primaryDocument": ["acme-8k.htm"],
                            "primaryDocDescription": ["Current report"],
                        }
                    },
                },
            )
        assert str(request.url) == filing_url
        return httpx.Response(200, text="<html><body>S2M listing approved.</body></html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    connector = build_connector(
        "SEC_EDGAR",
        policy_id=POLICY_ID,
        source_name="sec-test",
        policy_version="v1",
        trust_score=1,
        config={"cik": "123456", "user_agent": "Compliance compliance@example.com"},
        canonical_domains=["data.sec.gov", "www.sec.gov"],
        client=client,
        resolve_host=_public_dns,
    )
    try:
        filing = (await connector.fetch())[0]
    finally:
        await client.aclose()
    assert filing.body == "S2M listing approved."


async def test_connector_errors_are_explicit_and_rate_limits_classified() -> None:
    response = httpx.Response(
        429,
        request=httpx.Request("GET", "https://official.example/feed"),
    )
    connector = _connector("RSS_ATOM", {"url": "https://official.example/feed"}, response)
    with pytest.raises(ConnectorError) as captured:
        await connector.fetch()
    assert captured.value.rate_limited is True


async def test_connector_uses_conditional_headers_and_accepts_not_modified() -> None:
    seen: httpx.Request | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request
        return httpx.Response(304, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    connector = build_connector(
        "RSS_ATOM",
        policy_id=POLICY_ID,
        source_name="official-test",
        policy_version="v1",
        trust_score=1,
        config={"url": "https://official.example/feed"},
        canonical_domains=["official.example"],
        client=client,
        resolve_host=_public_dns,
    )
    try:
        batch = await connector.fetch(
            {
                "etag": '"old"',
                "last_modified": "yesterday",
                "source_watermark": ALERT.isoformat(),
            }
        )
    finally:
        await client.aclose()
    assert seen is not None
    assert seen.headers["if-none-match"] == '"old"'
    assert seen.headers["if-modified-since"] == "yesterday"
    assert batch.documents == []
    assert batch.checkpoint["etag"] == '"old"'
    assert batch.source_watermark == ALERT


@pytest.mark.parametrize(
    "url,domains",
    [
        ("http://official.example/feed", ["official.example"]),
        ("https://127.0.0.1/feed", ["127.0.0.1"]),
        ("https://169.254.169.254/latest", ["169.254.169.254"]),
        ("https://evil.example/feed", ["official.example"]),
    ],
)
async def test_connector_rejects_noncanonical_or_unsafe_urls(url: str, domains: list[str]) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    connector = build_connector(
        "RSS_ATOM",
        policy_id=POLICY_ID,
        source_name="official-test",
        policy_version="v1",
        trust_score=1,
        config={"url": url},
        canonical_domains=domains,
        client=client,
        resolve_host=_public_dns,
    )
    try:
        with pytest.raises(ConnectorError):
            await connector.fetch()
    finally:
        await client.aclose()


async def test_sec_validates_cik_and_skips_seen_accessions() -> None:
    response = httpx.Response(
        200,
        json={
            "name": "Acme Corp",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000123456-26-000001"],
                    "form": ["8-K"],
                    "filingDate": ["2026-08-12"],
                    "primaryDocument": ["acme.htm"],
                }
            },
        },
        request=httpx.Request("GET", "https://data.sec.gov/submissions/CIK0000123456.json"),
    )
    connector = _connector(
        "SEC_EDGAR",
        {"cik": "123456", "user_agent": "Compliance compliance@example.com"},
        response,
    )
    batch = await connector.fetch({"seen_keys": ["0000123456-26-000001"]})
    assert batch.documents == []

    invalid = _connector(
        "SEC_EDGAR",
        {"cik": "12x", "user_agent": "Compliance compliance@example.com"},
        response,
    )
    with pytest.raises(ConnectorError, match="numeric CIK"):
        await invalid.fetch()


async def test_sec_caps_documents_and_retains_seen_accession_order() -> None:
    accessions = [f"0000123456-26-{index:06d}" for index in range(3)]
    response = httpx.Response(
        200,
        json={
            "name": "Acme Corp",
            "filings": {
                "recent": {
                    "accessionNumber": accessions,
                    "form": ["8-K"] * 3,
                    "filingDate": ["2026-08-12"] * 3,
                    "primaryDocument": [""] * 3,
                }
            },
        },
        request=httpx.Request("GET", "https://data.sec.gov/submissions/CIK0000123456.json"),
    )
    connector = _connector(
        "SEC_EDGAR",
        {
            "cik": "123456",
            "user_agent": "Compliance compliance@example.com",
            "max_documents_per_run": 1,
        },
        response,
    )
    batch = await connector.fetch({"seen_keys": [accessions[2]]})
    assert [item.source_document_id for item in batch.documents] == [accessions[0]]
    assert batch.checkpoint["seen_keys"] == [accessions[0], accessions[2]]


def test_domain_defaults_only_apply_when_policy_domains_are_empty() -> None:
    client = _client(httpx.Response(200))
    github = build_connector(
        "GITHUB_RELEASES",
        policy_id=POLICY_ID,
        source_name="github",
        policy_version="v1",
        trust_score=1,
        config={"repository": "acme/project"},
        canonical_domains=[],
        client=client,
        resolve_host=_public_dns,
    )
    assert github is not None
    with pytest.raises(ConnectorError, match="requires canonical_domains"):
        build_connector(
            "RSS_ATOM",
            policy_id=POLICY_ID,
            source_name="feed",
            policy_version="v1",
            trust_score=1,
            config={"url": "https://official.example/feed"},
            canonical_domains=[],
            client=client,
            resolve_host=_public_dns,
        )


async def test_connector_rejects_canonical_host_resolving_to_private_address() -> None:
    client = _client(httpx.Response(200))
    connector = build_connector(
        "RSS_ATOM",
        policy_id=POLICY_ID,
        source_name="feed",
        policy_version="v1",
        trust_score=1,
        config={"url": "https://official.example/feed"},
        canonical_domains=["official.example"],
        client=client,
        resolve_host=lambda host: ["127.0.0.1"],
    )
    try:
        with pytest.raises(ConnectorError, match="resolved to a non-public"):
            await connector.fetch()
    finally:
        await client.aclose()


def test_source_policy_window_cannot_be_backdated_or_inverted() -> None:
    now = datetime.now(tz=UTC)
    with pytest.raises(HTTPException, match="backdated"):
        _validate_policy_window(now - timedelta(seconds=1), None, now)
    with pytest.raises(HTTPException, match="after effective_from"):
        _validate_policy_window(now + timedelta(seconds=1), now, now)


def _claim(amount: str = "10") -> Claim:
    text = f"S2M exchange listing partnership worth {amount} million"
    return Claim(
        claim_id=uuid5(NAMESPACE_URL, text),
        narrative_id=uuid5(NAMESPACE_URL, "phase-8-narrative"),
        asset_id="S2M",
        claim_text=text,
        claim_type="EXCHANGE_LISTING",
        canonical_payload={"polarity": "POSITIVE", "amounts": [amount]},
        claim_hash=hashlib.sha256(text.encode()).hexdigest(),
        extracted_at=ALERT,
        extractor_version="test",
    )


def _document(key: str, body: str, available_at: datetime) -> DisclosureDocument:
    content_hash = hashlib.sha256(body.encode()).hexdigest()
    return DisclosureDocument(
        disclosure_id=uuid5(NAMESPACE_URL, f"{key}:{content_hash}"),
        source="official-test",
        source_document_id=key,
        source_document_key=key,
        source_policy_id=POLICY_ID,
        asset_id="S2M",
        title="S2M exchange listing partnership",
        body=body,
        published_at=ALERT - timedelta(hours=2),
        retrieved_at=available_at,
        first_observed_at=available_at,
        ingested_at=available_at,
        available_at=available_at,
        reliability=1,
        content_hash=content_hash,
    )


async def _verification_services() -> tuple[
    InMemoryVerificationRepository, DisclosureIngestionService
]:
    repository = InMemoryVerificationRepository()
    ingestion = DisclosureIngestionService(
        repository=repository,
        embedding=DeterministicHashEmbedding(64),
        vector_index=InMemoryVectorIndex(),
    )
    return repository, ingestion


async def test_delayed_availability_is_retrospective_and_equality_supports() -> None:
    repository, ingestion = await _verification_services()
    delayed = _document(
        "delayed",
        "S2M exchange listing partnership worth 10 million",
        ALERT + timedelta(seconds=1),
    )
    await ingestion.ingest(delayed)
    result = await TimeBoundedClaimVerifier(repository, support_threshold=0.8).verify(
        _claim(), ALERT
    )
    assert result.result == VerificationResult.supported_after_alert
    assert result.evidence[0].relation == EvidenceRelation.retrospective
    assert result.claim_risk >= 0.7

    repository, ingestion = await _verification_services()
    equality = _document("equality", "S2M exchange listing partnership worth 10 million", ALERT)
    await ingestion.ingest(equality)
    result = await TimeBoundedClaimVerifier(repository, support_threshold=0.8).verify(
        _claim(), ALERT
    )
    assert result.result == VerificationResult.supported_before_alert
    assert result.evidence[0].temporal_eligible is True


async def test_connector_ingestion_time_prevents_pre_alert_support() -> None:
    repository, ingestion = await _verification_services()
    retrieved_before_alert = _document(
        "retrieved-before",
        "S2M exchange listing partnership worth 10 million",
        ALERT - timedelta(seconds=1),
    )
    await ingestion.ingest(retrieved_before_alert, assign_version=True, preserve_timestamps=False)
    persisted = next(iter(repository.documents.values()))[0]
    assert persisted.ingested_at is not None
    assert persisted.ingested_at > retrieved_before_alert.retrieved_at
    assert persisted.available_at == persisted.ingested_at


async def test_replay_ingestion_explicitly_preserves_timestamps() -> None:
    repository, ingestion = await _verification_services()
    replayed = _document(
        "replayed",
        "S2M exchange listing partnership worth 10 million",
        ALERT - timedelta(days=1),
    )
    await ingestion.ingest(replayed, assign_version=True, preserve_timestamps=True)
    persisted = next(iter(repository.documents.values()))[0]
    assert persisted.ingested_at == replayed.ingested_at
    assert persisted.available_at == replayed.available_at


async def test_latest_available_version_replaces_old_content_at_cutoff() -> None:
    repository, ingestion = await _verification_services()
    old = _document(
        "versioned",
        "S2M exchange listing partnership worth 10 million",
        ALERT - timedelta(hours=2),
    ).model_copy(update={"document_version": 1, "logical_source_key": "official-lineage"})
    amendment = _document(
        "versioned",
        "S2M exchange listing partnership worth 20 million",
        ALERT + timedelta(hours=1),
    ).model_copy(update={"document_version": 2, "logical_source_key": "official-lineage"})
    await ingestion.ingest(old)
    await ingestion.ingest(amendment)

    before = await TimeBoundedClaimVerifier(repository, support_threshold=0.8).verify(
        _claim(), ALERT
    )
    assert before.result == VerificationResult.supported_before_alert
    after = await TimeBoundedClaimVerifier(repository).verify(_claim(), ALERT + timedelta(hours=2))
    assert after.result == VerificationResult.conflicting
    assert str(old.disclosure_id) not in after.evidence_document_ids


async def test_outage_degrades_no_support_to_unknown() -> None:
    repository, ingestion = await _verification_services()
    repository.coverage = {
        "expected_source_count": 1,
        "degraded_source_count": 1,
        "degraded_sources": [{"status": "FAILED"}],
        "complete": False,
    }
    await ingestion.ingest(
        _document("unrelated", "Routine wallet maintenance for another asset", ALERT)
    )
    result = await TimeBoundedClaimVerifier(repository, support_threshold=0.8).verify(
        _claim(), ALERT
    )
    assert result.result == VerificationResult.unknown
    coverage = cast(dict[str, object], result.retrieval_metadata["coverage"])
    assert coverage["complete"] is False


async def test_unrelated_asset_outage_does_not_degrade_coverage() -> None:
    repository, ingestion = await _verification_services()
    repository.coverage_by_asset["OTHER"] = {
        "expected_source_count": 1,
        "degraded_source_count": 1,
        "degraded_sources": [{"status": "FAILED"}],
        "complete": False,
    }
    await ingestion.ingest(
        _document("unrelated", "Routine wallet maintenance for another asset", ALERT)
    )
    result = await TimeBoundedClaimVerifier(repository, support_threshold=0.8).verify(
        _claim(), ALERT
    )
    coverage = cast(dict[str, object], result.retrieval_metadata["coverage"])
    assert coverage["complete"] is True


async def test_supporting_conflicting_and_future_amendment_are_preserved() -> None:
    repository, ingestion = await _verification_services()
    await ingestion.ingest(
        _document("support", "S2M exchange listing partnership worth 10 million", ALERT)
    )
    await ingestion.ingest(
        _document("conflict", "S2M exchange listing partnership worth 20 million", ALERT)
    )
    await ingestion.ingest(
        _document(
            "amendment",
            "S2M exchange listing partnership worth 10 million amended",
            ALERT + timedelta(hours=1),
        )
    )
    result = await TimeBoundedClaimVerifier(repository).verify(_claim(), ALERT)
    relations = {item.relation for item in result.evidence}
    assert result.result == VerificationResult.conflicting
    assert relations == {
        EvidenceRelation.supporting,
        EvidenceRelation.conflicting,
        EvidenceRelation.retrospective,
    }
    conflict = next(
        item for item in result.evidence if item.relation == EvidenceRelation.conflicting
    )
    assert "AMOUNT_MISMATCH" in conflict.reason_codes


def test_openapi_contains_phase_8_paths() -> None:
    from scam2market.main import create_app

    paths = create_app().openapi()["paths"]
    expected = {
        "/api/v1/claims/{claim_id}",
        "/api/v1/claims/{claim_id}/verification",
        "/api/v1/alerts/{alert_id}/claims",
        "/api/v1/disclosures/{disclosure_id}",
        "/api/v1/disclosures/{disclosure_id}/versions",
        "/api/v1/verification/timeline",
        "/api/v1/source-policies",
        "/api/v1/source-connectors/runs",
    }
    assert expected <= set(paths)
    patch_schema = paths["/api/v1/source-policies/{source_policy_id}"]["patch"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    assert patch_schema["$ref"].endswith("/SourcePolicyPatch")
    schema = create_app().openapi()["components"]["schemas"]["SourcePolicyPatch"]
    assert "policy_version" in schema["required"]
