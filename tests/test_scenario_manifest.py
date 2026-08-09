from scam2market.features.manifest import load_feature_manifest
from scam2market.ingestion.scenarios import load_scenario_manifest


def test_demo_scenario_declares_deterministic_counts_and_thresholds() -> None:
    manifest = load_scenario_manifest()

    assert manifest.scenario_id == "synthetic-pump-v1"
    assert manifest.expected_event_counts.market == 26
    assert manifest.expected_event_counts.social == 6
    assert manifest.expectations.watch_before < manifest.expectations.high_before


def test_feature_manifest_has_stable_ordered_hash() -> None:
    first = load_feature_manifest()
    second = load_feature_manifest()

    assert first.ordered_features == second.ordered_features
    assert first.schema_hash == second.schema_hash
    assert len(first.schema_hash) == 64
