from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from scam2market.ingestion.archive import ParquetRawEventArchive
from scam2market.schemas.events import CanonicalEvent, EventType


async def test_raw_archive_writes_immutable_parquet_event(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    event = CanonicalEvent(
        event_id="archive-event-1",
        event_type=EventType.market_trade_received,
        schema_version=1,
        source="archive-test",
        source_event_id="trade-1",
        source_sequence=1,
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        partition_key="S2MUSDT",
        payload={"price": 1.0, "quantity": 10.0},
    )
    archive = ParquetRawEventArchive(tmp_path)

    await archive.write("market", event)
    await archive.write("market", event)

    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1
    row = pq.read_table(files[0]).to_pylist()[0]
    assert row["event_id"] == event.event_id
    assert row["source_event_id"] == event.source_event_id
    assert row["event_time"] == event.event_time
