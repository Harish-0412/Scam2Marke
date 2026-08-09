from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum


class OrderBookState(StrEnum):
    valid = "VALID"
    stale = "STALE"
    gap_detected = "GAP_DETECTED"
    resyncing = "RESYNCING"
    recovered = "RECOVERED"


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
    source_active: bool = False
    source_idle: bool = False
    source_degraded: bool = False
    orderbook_state: OrderBookState = OrderBookState.valid
    book_valid: bool = True
    recovery_updates: int = 0

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
        is_orderbook: bool = False,
    ) -> SourceQuality:
        state = self._states.setdefault((source, asset_id), SourceQuality(source, asset_id))
        gap_detected = False
        if sequence is not None and state.last_sequence is not None:
            if sequence > state.last_sequence + 1:
                state.sequence_gap_count += sequence - state.last_sequence - 1
                gap_detected = True
            elif sequence <= state.last_sequence:
                state.out_of_order_count += 1
                gap_detected = True
        if sequence is not None:
            state.last_sequence = max(sequence, state.last_sequence or sequence)
        state.last_event_time = max(event_time, state.last_event_time or event_time)
        state.last_ingested_at = ingested_at
        age = max(0.0, (ingested_at - event_time).total_seconds())
        state.source_active = True
        state.source_idle = False
        if is_orderbook:
            if age > self._threshold:
                state.orderbook_state = OrderBookState.stale
                state.recovery_updates = 0
            elif gap_detected:
                state.orderbook_state = OrderBookState.gap_detected
                state.recovery_updates = 0
            elif state.orderbook_state in {
                OrderBookState.gap_detected,
                OrderBookState.stale,
            }:
                state.orderbook_state = OrderBookState.resyncing
                state.recovery_updates = 1
            elif state.orderbook_state == OrderBookState.resyncing:
                state.orderbook_state = OrderBookState.recovered
                state.recovery_updates += 1
            elif state.orderbook_state == OrderBookState.recovered:
                state.orderbook_state = OrderBookState.valid
            state.book_valid = state.orderbook_state in {
                OrderBookState.valid,
                OrderBookState.recovered,
            }
        state.source_degraded = (
            age > self._threshold or gap_detected or (is_orderbook and not state.book_valid)
        )
        state.status = "DEGRADED" if state.source_degraded else "HEALTHY"
        return state

    def mark_idle(self, source: str, asset_id: str) -> SourceQuality:
        state = self._states.setdefault((source, asset_id), SourceQuality(source, asset_id))
        state.source_active = True
        state.source_idle = True
        state.source_degraded = False
        state.status = "IDLE"
        return state

    def get(self, source: str, asset_id: str) -> SourceQuality | None:
        return self._states.get((source, asset_id))
