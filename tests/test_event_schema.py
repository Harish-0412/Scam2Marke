from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata


def test_canonical_event_contains_required_temporal_fields() -> None:
    now = datetime.now(tz=UTC)
    event = CanonicalEvent(
        event_type=EventType.market_trade_received,
        schema_version=1,
        source="synthetic",
        source_event_id="trade-1",
        source_sequence=1,
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        partition_key="S2MUSDT",
        payload={"price": 1.0, "quantity": 10.0},
    )

    assert event.event_time == now
    assert event.ingested_at == now
    assert event.processed_at is None
    assert event.origin_event_id == "synthetic:trade-1"
    assert event.delivery_event_id == event.event_id
    assert event.dedupe_key() == event.delivery_event_id


def test_replay_event_requires_replay_session_id() -> None:
    with pytest.raises(ValidationError):
        ReplayMetadata(is_replay=True)


def test_partition_key_cannot_be_blank() -> None:
    now = datetime.now(tz=UTC)

    with pytest.raises(ValidationError):
        CanonicalEvent(
            event_type=EventType.social_post_received,
            schema_version=1,
            source="synthetic-social",
            source_event_id="post-1",
            event_time=now,
            ingested_at=now,
            partition_key=" ",
            payload={"text": "$S2M is moving"},
        )
