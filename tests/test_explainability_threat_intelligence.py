from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest

from scam2market.features.schemas import (
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    FeatureLineage,
    FeatureSnapshot,
    RevisionState,
)
from scam2market.intelligence.detectors import MarketAnomalyDetector, SocialSurgeDetector
from scam2market.intelligence.fusion import (
    ContributionDirection,
    FusionEngine,
    ThreatContext,
    ThreatContextStatus,
)
from scam2market.intelligence.otx_client import OTXClient, OTXRateLimited
from scam2market.intelligence.repository import IntelligenceRepository
from scam2market.intelligence.threat import IndicatorType, match_candidates, normalize_indicator
from scam2market.main import app


def _snapshot(**overrides: float | int | None) -> FeatureSnapshot:
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    features: dict[str, float | int | None] = {name: 0.0 for name in FEATURE_NAMES}
    features.update(
        {
            "spread": None,
            "top_n_depth": None,
            "orderbook_imbalance": None,
            "social_lead_seconds": None,
            "data_quality_score": 1.0,
            "baseline_confidence": 0.8,
            **overrides,
        }
    )
    return FeatureSnapshot(
        feature_window_id=uuid5(NAMESPACE_URL, "explainability-threat-window"),
        asset_id="S2MUSDT",
        window_start=start,
        window_end=start + timedelta(minutes=1),
        interval_seconds=60,
        revision=1,
        is_final=True,
        revision_state=RevisionState.final,
        feature_schema_version=FEATURE_SCHEMA.feature_schema,
        features=features,
        lineage=FeatureLineage(
            lineage_id=uuid5(NAMESPACE_URL, "explainability-threat-lineage"),
            source_event_ids=["event-1"],
            source_event_min_time=start,
            source_event_max_time=start,
            source_count=1,
            source_hash="a" * 64,
        ),
    )


def _fuse(*, legitimate: float | None = None, threat: ThreatContext | None = None):
    snapshot = _snapshot(
        price_return=0.3,
        relative_volume=7,
        volatility=0.1,
        trade_count=40,
        mention_count=20,
        unique_author_count=10,
        hashtag_velocity=15,
    )
    return FusionEngine().fuse(
        snapshot,
        [MarketAnomalyDetector().score(snapshot), SocialSurgeDetector().score(snapshot)],
        legitimate_event_score=legitimate,
        threat_context=threat,
        market_regime="DISLOCATED",
        market_regime_confidence=0.9,
        liquidity_class="LOW",
        liquidity_confidence=0.8,
    )


def test_decision_trace_reproduces_raw_score_and_renormalizes_missing_components() -> None:
    result = _fuse()
    trace = result.decision_trace

    assert sum(item.signed_weighted_contribution for item in trace.components) == pytest.approx(
        trace.raw_weighted_score
    )
    available = [item for item in trace.components if not item.missing]
    assert sum(item.effective_normalized_weight for item in available) == pytest.approx(1.0)
    assert all(item.effective_normalized_weight == 0 for item in trace.components if item.missing)


def test_legitimate_event_is_risk_reducing_and_policy_caps_are_traced() -> None:
    result = _fuse(legitimate=1.0)
    adjustment = next(
        item for item in result.decision_trace.adjustments if item.name == "legitimate_event"
    )

    assert adjustment.direction == ContributionDirection.risk_reducing
    assert adjustment.after < adjustment.before
    assert any(
        item.policy == "market_evidence_high_cap" for item in result.decision_trace.policy_decisions
    )


def test_threat_uplift_is_bounded_and_cannot_independently_raise_high() -> None:
    baseline = _fuse()
    matched = _fuse(
        threat=ThreatContext(status=ThreatContextStatus.matched, score=1.0, confidence=1.0)
    )

    assert 0 <= matched.fusion_score - baseline.fusion_score <= 0.10
    if baseline.fusion_score < 0.60:
        assert matched.fusion_score < 0.60


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("domain", "Example.COM.", "example.com"),
        ("URL", "HTTPS://Example.com/path#fragment", "https://example.com/path"),
        ("IPv4", "192.0.2.1", "192.0.2.1"),
        ("IPv6", "2001:0db8::1", "2001:db8::1"),
        ("SHA256", "A" * 64, "a" * 64),
        ("email", "User@Example.COM", "user@example.com"),
    ],
)
def test_indicator_normalization(kind: str, raw: str, expected: str) -> None:
    assert normalize_indicator(kind, raw).value == expected


def test_exact_url_domain_ip_and_hash_candidates() -> None:
    sha = "a" * 64
    candidates = match_candidates(
        f"See bad.example and 192.0.2.2 hash {sha}", ["https://bad.example/path"]
    )
    assert (IndicatorType.url, "https://bad.example/path") in candidates
    assert (IndicatorType.domain, "bad.example") in candidates
    assert (IndicatorType.ipv4, "192.0.2.2") in candidates
    assert (IndicatorType.sha256, sha) in candidates


def test_candidate_post_query_is_bounded_by_indicator_value() -> None:
    query = IntelligenceRepository(None)._candidate_post_query("DOMAIN", "bad.example")
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))

    assert "lower(social_posts.text) LIKE lower('%bad.example%')" in compiled
    assert "post_asset_mentions.asset_id IS NOT NULL" in compiled


async def test_feed_watermark_accepts_z_suffix() -> None:
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *_args: object):
            return type(
                "Status",
                (),
                {"checkpoint_json": {"modified_since": "2026-08-12T00:00:00Z"}},
            )()

    parsed = await IntelligenceRepository(lambda: FakeSession()).feed_modified_since()

    assert parsed == datetime(2026, 8, 12, tzinfo=UTC)


async def test_otx_realistic_parsing_header_malformed_isolation_and_pagination_bound() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {
                        "id": "pulse-1",
                        "name": "Observed phishing",
                        "modified": "2026-08-12T00:00:00Z",
                        "TLP": "amber",
                        "tags": ["phishing"],
                        "indicators": [
                            {
                                "id": "indicator-1",
                                "type": "domain",
                                "indicator": "bad.example",
                                "created": "2026-08-11T00:00:00Z",
                            }
                        ],
                    },
                    {"id": "malformed"},
                ],
                "next": "https://otx.alienvault.com/api/v1/pulses/subscribed?page=2",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = OTXClient("secret", client=http_client)
        pulses = [pulse async for pulse in client.fetch_pulses(max_pages=1)]
    assert len(pulses) == 1
    assert requests[0].headers["X-OTX-API-KEY"] == "secret"
    assert len(requests) == 1


async def test_otx_rejects_cross_host_cursor_and_classifies_429() -> None:
    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, request=request, json={"results": [], "next": "https://evil.test/steal"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)) as http_client:
        with pytest.raises(ValueError, match="fixed HTTPS OTX host"):
            await OTXClient("secret", client=http_client).fetch_page()

    def rate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request, headers={"Retry-After": "30"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_handler)) as http_client:
        with pytest.raises(OTXRateLimited) as raised:
            await OTXClient("secret", client=http_client).fetch_page()
    assert raised.value.retry_after == 30.0


def test_openapi_contains_explainability_and_threat_paths() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/model-scores/{model_score_id}/explanation",
        "/api/v1/intelligence/threat/indicators",
        "/api/v1/intelligence/assets/{asset_id}/threat-context",
        "/api/v1/intelligence/threat/matches/{match_id}",
        "/api/v1/intelligence/threat/feed-status",
    }
    assert expected <= paths.keys()


def test_prototypes_ports_and_optional_model_dependencies_are_absent() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    project = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "8001:8001" not in compose
    assert "8002:8002" not in compose
    assert "explainability-service:" not in compose
    assert "threat-feed-service:" not in compose
    assert "shap" not in project.lower()
    assert "joblib" not in project.lower()
