from datetime import UTC, datetime
from uuid import UUID

from scam2market.evidence.schemas import EvidenceInput
from scam2market.evidence.service import EvidenceBuilder


def _input(*, version: int = 1, graph: bool = True) -> EvidenceInput:
    cutoff = datetime(2026, 1, 1, 12, 2, tzinfo=UTC)
    return EvidenceInput(
        alert_id=UUID("11111111-1111-1111-1111-111111111111"),
        campaign_id=UUID("22222222-2222-2222-2222-222222222222"),
        scope_id="replay-1",
        asset_id="S2MUSDT",
        alert_version=version,
        alert_type="CROSS_DOMAIN_MANIPULATION_RISK",
        severity="HIGH",
        stage="MARKET_PUMP",
        evidence_cutoff=cutoff,
        campaign_evidence_event_id=f"evidence-{version}",
        fusion={
            "feature_window_id": "33333333-3333-3333-3333-333333333333",
            "feature_revision": 2,
            "model_version": "fusion-v2",
            "fusion_policy_version": "fusion-policy-v1",
            "fusion_score": 0.74,
            "market_score": 0.81,
            "social_score": 0.71,
            "coordination_score": 0.78,
            "temporal_score": 0.62,
            "graph_score": 0.73 if graph else None,
            "claim_risk": 0.8,
            "legitimate_event_score": 0.0,
        },
        feature={
            "feature_window_id": "33333333-3333-3333-3333-333333333333",
            "revision": 2,
            "feature_schema_hash": "a" * 64,
        },
        feature_lineage={"source_hash": "b" * 64, "source_count": 20},
        narrative={
            "narrative_id": "44444444-4444-4444-4444-444444444444",
            "post_count": 18,
        },
        graph=(
            {
                "graph_snapshot_id": "55555555-5555-5555-5555-555555555555",
                "features": {"community_concentration": 0.9},
            }
            if graph
            else None
        ),
        verifications=[
            {
                "verification_id": "66666666-6666-6666-6666-666666666666",
                "result": "UNSUPPORTED",
            }
        ],
    )


def test_evidence_snapshot_is_deterministic_and_content_addressed() -> None:
    created_at = datetime(2026, 1, 1, 12, 3, tzinfo=UTC)
    first = EvidenceBuilder().build(_input(), previous_chain_hash=None, created_at=created_at)
    second = EvidenceBuilder().build(_input(), previous_chain_hash=None, created_at=created_at)

    assert first == second
    snapshot, explanation = first
    assert snapshot.completeness_score == 1.0
    assert snapshot.content_hash != snapshot.chain_hash
    assert len(snapshot.references) == 5
    assert explanation.llm_status == "NOT_REQUESTED"
    assert explanation.contributors[0]["feature"] == "market_score"
    assert "HIGH" in explanation.summary


def test_evidence_chain_and_completeness_expose_missing_components() -> None:
    now = datetime(2026, 1, 1, 12, 4, tzinfo=UTC)
    previous, _ = EvidenceBuilder().build(_input(), previous_chain_hash=None, created_at=now)
    current, _ = EvidenceBuilder().build(
        _input(version=2, graph=False),
        previous_chain_hash=previous.chain_hash,
        created_at=now,
    )

    assert current.previous_chain_hash == previous.chain_hash
    assert current.chain_hash != previous.chain_hash
    assert current.completeness_score < 1.0
    assert "graph" in current.completeness["missing"]
