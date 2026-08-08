from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(slots=True)
class SourceQuality:
    source: str
    asset_id: str
    last_event_time: datetime | None = None
    last_ingested_at: datetime | None = None
    last_sequence: int | None = None
    sequence_gap_count: int = 0
    out_of_order_count: int = 0
    status: str = "STARTING"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class SourceQualityTracker:
    def __init__(self, freshness_threshold_seconds: int) -> None:
        self._threshold = freshness_threshold_seconds
        self._states: dict[tuple[str, str], SourceQuality] = {}

    def observe(
        self,
        *,
        source: str,
        asset_id: str,
        event_time: datetime,
        ingested_at: datetime,
        sequence: int | None,
    ) -> SourceQuality:
        state = self._states.setdefault((source, asset_id), SourceQuality(source, asset_id))
        if sequence is not None and state.last_sequence is not None:
            if sequence > state.last_sequence + 1:
                state.sequence_gap_count += sequence - state.last_sequence - 1
            elif sequence <= state.last_sequence:
                state.out_of_order_count += 1
        if sequence is not None:
            state.last_sequence = max(sequence, state.last_sequence or sequence)
        state.last_event_time = max(event_time, state.last_event_time or event_time)
        state.last_ingested_at = ingested_at
        age = max(0.0, (ingested_at - event_time).total_seconds())
        state.status = (
            "DEGRADED" if state.sequence_gap_count > 0 or age > self._threshold else "HEALTHY"
        )
        return state

    def get(self, source: str, asset_id: str) -> SourceQuality | None:
        return self._states.get((source, asset_id))
