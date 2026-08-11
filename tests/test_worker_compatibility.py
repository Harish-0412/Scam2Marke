from scam2market.workers.evidence_worker import main as evidence_worker_main
from scam2market.workers.intelligence_worker import _verification_snapshot_id


def test_verification_snapshot_id_uses_explicit_identity() -> None:
    assert (
        _verification_snapshot_id({"verification_snapshot_id": "verification-123"}, "event-123")
        == "verification-123"
    )


def test_verification_snapshot_id_falls_back_for_legacy_event() -> None:
    assert _verification_snapshot_id({}, "legacy-event-123") == "legacy-event-123"


def test_evidence_worker_entrypoint_is_importable() -> None:
    assert callable(evidence_worker_main)
