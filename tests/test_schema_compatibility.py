from scam2market.schemas.events import CanonicalEvent


def test_canonical_event_json_schema_contains_phase_1_contract_fields() -> None:
    schema = CanonicalEvent.model_json_schema()
    properties = schema["properties"]

    expected = {
        "event_id",
        "event_type",
        "schema_version",
        "source",
        "source_event_id",
        "source_sequence",
        "asset_id",
        "event_time",
        "ingested_at",
        "processed_at",
        "partition_key",
        "replay",
        "trace",
        "payload",
    }

    assert expected.issubset(properties.keys())
