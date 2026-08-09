import asyncio
from pathlib import Path
from typing import Protocol

import orjson

from scam2market.schemas.events import CanonicalEvent


class RawEventArchive(Protocol):
    async def write(self, stream: str, event: CanonicalEvent) -> None: ...


class ParquetRawEventArchive:
    """Append-only archive using one immutable Parquet object per source event."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    async def write(self, stream: str, event: CanonicalEvent) -> None:
        await asyncio.to_thread(self._write_sync, stream, event)

    def _write_sync(self, stream: str, event: CanonicalEvent) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        partition = (
            self._root
            / stream
            / f"date={event.event_time.date().isoformat()}"
            / f"source={event.source}"
        )
        partition.mkdir(parents=True, exist_ok=True)
        destination = partition / f"{event.event_id}.parquet"
        if destination.exists():
            return
        row = {
            "event_id": [event.event_id],
            "origin_event_id": [event.origin_event_id],
            "delivery_event_id": [event.delivery_event_id],
            "event_type": [event.event_type.value],
            "asset_id": [event.asset_id],
            "event_time": [event.event_time],
            "ingested_at": [event.ingested_at],
            "source_event_id": [event.source_event_id],
            "source_sequence": [event.source_sequence],
            "envelope_json": [orjson.dumps(event.model_dump(mode="json")).decode("utf-8")],
        }
        pq.write_table(pa.table(row), destination, compression="zstd")


class InMemoryRawEventArchive:
    def __init__(self) -> None:
        self.events: list[tuple[str, CanonicalEvent]] = []

    async def write(self, stream: str, event: CanonicalEvent) -> None:
        self.events.append((stream, event))
