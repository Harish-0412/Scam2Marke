import hashlib
import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

import orjson

from scam2market.features.schemas import (
    FEATURE_NAMES,
    FeatureLineage,
    FeatureSignal,
    FeatureSnapshot,
    SignalKind,
)
from scam2market.schemas.events import (
    CanonicalEvent,
    EventType,
    ReplayMetadata,
    TraceMetadata,
)
from scam2market.state import OnlineStateStore
from scam2market.streaming.publisher import CanonicalEventPublisher


class FeatureRepository(Protocol):
    async def persist(self, snapshot: FeatureSnapshot) -> bool: ...


def _floor_window(value: datetime, interval_seconds: int) -> datetime:
    epoch_seconds = int(value.timestamp())
    floored = epoch_seconds - epoch_seconds % interval_seconds
    return datetime.fromtimestamp(floored, tz=UTC)


def _safe_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _concentration(values: Sequence[str]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    return max(counts.values()) / len(values)


class FeatureWindowEngine:
    def __init__(
        self,
        *,
        intervals_seconds: tuple[int, ...] = (60, 300),
        allowed_lateness_seconds: int = 120,
        feature_schema_version: str = "surveillance-features-v1",
    ) -> None:
        if not intervals_seconds or any(interval <= 0 for interval in intervals_seconds):
            raise ValueError("feature intervals must be positive")
        self._intervals = intervals_seconds
        self._allowed_lateness = timedelta(seconds=allowed_lateness_seconds)
        self._schema_version = feature_schema_version
        self._events: dict[tuple[str, str, datetime, int], list[FeatureSignal]] = {}
        self._revisions: dict[tuple[str, str, datetime, int], list[FeatureSnapshot]] = {}
        self._max_event_time: dict[tuple[str, str], datetime] = {}
        self._seen_event_ids: set[tuple[str, str]] = set()
        self._author_first_seen: dict[tuple[str, str, str], datetime] = {}

    def ingest(self, signal: FeatureSignal) -> list[FeatureSnapshot]:
        seen_key = (signal.scope_id, signal.event_id)
        if seen_key in self._seen_event_ids:
            return []
        self._seen_event_ids.add(seen_key)
        scope_asset = (signal.scope_id, signal.asset_id)
        self._max_event_time[scope_asset] = max(
            signal.event_time, self._max_event_time.get(scope_asset, signal.event_time)
        )
        author_id = signal.values.get("author_id")
        if isinstance(author_id, str):
            author_key = (signal.scope_id, signal.asset_id, author_id)
            self._author_first_seen[author_key] = min(
                signal.event_time, self._author_first_seen.get(author_key, signal.event_time)
            )

        changed: list[FeatureSnapshot] = []
        for interval in self._intervals:
            start = _floor_window(signal.event_time, interval)
            window_key = (signal.scope_id, signal.asset_id, start, interval)
            self._events.setdefault(window_key, []).append(signal)
            changed.append(self._build_revision(window_key))
            downstream_keys = sorted(
                (
                    candidate
                    for candidate in self._revisions
                    if candidate[0] == signal.scope_id
                    and candidate[1] == signal.asset_id
                    and candidate[3] == interval
                    and candidate[2] > start
                ),
                key=lambda candidate: candidate[2],
            )
            for downstream_key in downstream_keys:
                changed.append(
                    self._build_revision(
                        downstream_key,
                        force_final=self._revisions[downstream_key][-1].is_final,
                    )
                )
        changed.extend(self._finalize_eligible(signal.scope_id, signal.asset_id))
        return changed

    def revisions(
        self,
        asset_id: str,
        window_start: datetime,
        interval_seconds: int,
        scope_id: str = "LIVE",
    ) -> list[FeatureSnapshot]:
        return list(self._revisions.get((scope_id, asset_id, window_start, interval_seconds), []))

    def latest(
        self, asset_id: str, interval_seconds: int, scope_id: str = "LIVE"
    ) -> FeatureSnapshot | None:
        candidates = [
            revisions[-1]
            for (
                candidate_scope,
                candidate_asset,
                _,
                candidate_interval,
            ), revisions in self._revisions.items()
            if candidate_scope == scope_id
            and candidate_asset == asset_id
            and candidate_interval == interval_seconds
        ]
        return max(candidates, key=lambda item: item.window_start, default=None)

    def _watermark(self, scope_id: str, asset_id: str) -> datetime:
        return self._max_event_time[(scope_id, asset_id)] - self._allowed_lateness

    def _finalize_eligible(self, scope_id: str, asset_id: str) -> list[FeatureSnapshot]:
        finalized: list[FeatureSnapshot] = []
        watermark = self._watermark(scope_id, asset_id)
        for key, revisions in list(self._revisions.items()):
            candidate_scope, candidate_asset, start, interval = key
            if candidate_scope != scope_id or candidate_asset != asset_id or revisions[-1].is_final:
                continue
            if start + timedelta(seconds=interval) <= watermark:
                finalized.append(self._build_revision(key, force_final=True))
        return finalized

    def _build_revision(
        self, key: tuple[str, str, datetime, int], *, force_final: bool = False
    ) -> FeatureSnapshot:
        scope_id, asset_id, window_start, interval = key
        window_end = window_start + timedelta(seconds=interval)
        events = sorted(self._events[key], key=lambda event: (event.event_time, event.event_id))
        prior = self._revisions.get(key, [])
        revision = len(prior) + 1
        is_final = force_final or window_end <= self._watermark(scope_id, asset_id)
        event_ids = [event.event_id for event in events]
        source_material = orjson.dumps(
            [event.model_dump(mode="json") for event in events], option=orjson.OPT_SORT_KEYS
        )
        source_hash = hashlib.sha256(source_material).hexdigest()
        window_id = uuid5(NAMESPACE_URL, f"feature:{scope_id}:{asset_id}:{window_start}:{interval}")
        lineage_id = uuid5(NAMESPACE_URL, f"lineage:{window_id}:{revision}:{source_hash}")
        snapshot = FeatureSnapshot(
            feature_window_id=window_id,
            scope_id=scope_id,
            asset_id=asset_id,
            window_start=window_start,
            window_end=window_end,
            interval_seconds=interval,
            revision=revision,
            is_final=is_final,
            feature_schema_version=self._schema_version,
            features=self._compute_features(scope_id, asset_id, window_start, window_end, events),
            lineage=FeatureLineage(
                lineage_id=lineage_id,
                source_event_ids=event_ids,
                source_event_min_time=events[0].event_time if events else None,
                source_event_max_time=events[-1].event_time if events else None,
                source_count=len(events),
                source_hash=source_hash,
            ),
        )
        self._revisions.setdefault(key, []).append(snapshot)
        return snapshot

    def _compute_features(
        self,
        scope_id: str,
        asset_id: str,
        window_start: datetime,
        window_end: datetime,
        events: Sequence[FeatureSignal],
    ) -> dict[str, float | int | None]:
        trades = [event for event in events if event.kind == SignalKind.market_trade]
        candles = [event for event in events if event.kind == SignalKind.market_candle]
        books = [event for event in events if event.kind == SignalKind.orderbook]
        social = [event for event in events if event.kind == SignalKind.social_post]
        mentions = [event for event in events if event.kind == SignalKind.asset_mention]
        quality = [event for event in events if event.kind == SignalKind.data_quality]

        prices = [_safe_float(event.values.get("price")) for event in trades]
        if not prices:
            prices = [_safe_float(event.values.get("close")) for event in candles]
        price_return = prices[-1] / prices[0] - 1.0 if len(prices) > 1 and prices[0] else 0.0
        returns = [
            prices[index] / prices[index - 1] - 1.0
            for index in range(1, len(prices))
            if prices[index - 1]
        ]
        volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        trade_volume = sum(
            _safe_float(event.values.get("quantity")) * _safe_float(event.values.get("price"), 1.0)
            for event in trades
        )
        candle_volume = sum(_safe_float(event.values.get("volume")) for event in candles)
        volume = trade_volume or candle_volume
        interval_seconds = int((window_end - window_start).total_seconds())
        trailing_volumes = [
            self._raw_volume(candidate_events)
            for (
                candidate_scope,
                candidate_asset,
                candidate_start,
                candidate_interval,
            ), candidate_events in sorted(self._events.items(), key=lambda item: item[0][2])
            if candidate_scope == scope_id
            and candidate_asset == asset_id
            and candidate_interval == interval_seconds
            and candidate_start < window_start
        ][-20:]
        trailing_volumes = [value for value in trailing_volumes if value > 0]
        baseline_volume_values = [
            _safe_float(event.values.get("baseline_volume"))
            for event in events
            if _safe_float(event.values.get("baseline_volume")) > 0
        ]
        baseline_volume = (
            statistics.fmean(baseline_volume_values)
            if baseline_volume_values
            else statistics.fmean(trailing_volumes)
            if trailing_volumes
            else volume
        )
        relative_volume = volume / baseline_volume if baseline_volume else 0.0

        spreads = [_safe_float(event.values.get("spread")) for event in books]
        depths = [_safe_float(event.values.get("top_n_depth")) for event in books]
        imbalances = [_safe_float(event.values.get("imbalance")) for event in books]
        buys = sum(
            _safe_float(event.values.get("quantity"))
            for event in trades
            if event.values.get("side") == "BUY"
        )
        sells = sum(
            _safe_float(event.values.get("quantity"))
            for event in trades
            if event.values.get("side") == "SELL"
        )
        pressure = (buys - sells) / (buys + sells) if buys + sells else 0.0

        authors = [
            author for event in social if isinstance((author := event.values.get("author_id")), str)
        ]
        urls = [
            str(url)
            for event in social
            for url in event.values.get("urls", [])
            if isinstance(url, str)
        ]
        repost_reply_count = sum(
            int(bool(event.values.get("repost_of") or event.values.get("reply_to")))
            for event in social
        )
        hashtag_count = sum(
            len(event.values.get("hashtags", [])) + len(event.values.get("cashtags", []))
            for event in social
        )
        new_author_count = sum(
            self._author_first_seen.get((scope_id, asset_id, author), window_start) >= window_start
            for author in set(authors)
        )
        source_gap_count = int(
            max(
                (_safe_float(event.values.get("source_gap_count")) for event in quality),
                default=0.0,
            )
        )

        market_times = [event.event_time for event in trades + candles + books]
        social_times = [event.event_time for event in social + mentions]
        market_freshness = (
            max(0.0, (window_end - max(market_times)).total_seconds())
            if market_times
            else float((window_end - window_start).total_seconds())
        )
        social_freshness = (
            max(0.0, (window_end - max(social_times)).total_seconds())
            if social_times
            else float((window_end - window_start).total_seconds())
        )
        social_lead = (
            (min(market_times) - min(social_times)).total_seconds()
            if market_times and social_times
            else None
        )
        freshness_penalty = min(1.0, (market_freshness + social_freshness) / 600.0)
        data_quality_score = max(0.0, 1.0 - freshness_penalty - min(0.5, source_gap_count * 0.1))
        prior_window_count = sum(
            1
            for (
                candidate_scope,
                candidate_asset,
                candidate_start,
                candidate_interval,
            ) in self._events
            if candidate_scope == scope_id
            and candidate_asset == asset_id
            and candidate_start < window_start
            and candidate_interval == interval_seconds
        )

        values: dict[str, float | int | None] = {
            "price_return": price_return,
            "volume": volume,
            "relative_volume": relative_volume,
            "volatility": volatility,
            "spread": statistics.fmean(spreads) if spreads else None,
            "top_n_depth": statistics.fmean(depths) if depths else None,
            "orderbook_imbalance": statistics.fmean(imbalances) if imbalances else None,
            "trade_count": len(trades),
            "buy_sell_pressure": pressure,
            "market_data_freshness_seconds": market_freshness,
            "mention_count": len(mentions),
            "unique_author_count": len(set(authors)),
            "author_concentration": _concentration(authors),
            "repost_reply_ratio": repost_reply_count / len(social) if social else 0.0,
            "hashtag_velocity": hashtag_count
            / max(1.0, (window_end - window_start).total_seconds() / 60),
            "url_concentration": _concentration(urls),
            "new_author_ratio": new_author_count / len(set(authors)) if authors else 0.0,
            "social_data_freshness_seconds": social_freshness,
            "social_lead_seconds": social_lead,
            "source_gap_count": source_gap_count,
            "data_quality_score": data_quality_score,
            "baseline_confidence": min(1.0, prior_window_count / 20.0),
        }
        return {name: values[name] for name in FEATURE_NAMES}

    @staticmethod
    def _raw_volume(events: Sequence[FeatureSignal]) -> float:
        trades = [event for event in events if event.kind == SignalKind.market_trade]
        candles = [event for event in events if event.kind == SignalKind.market_candle]
        trade_volume = sum(
            _safe_float(event.values.get("quantity")) * _safe_float(event.values.get("price"), 1.0)
            for event in trades
        )
        return trade_volume or sum(_safe_float(event.values.get("volume")) for event in candles)


class FeatureWindowService:
    def __init__(
        self,
        *,
        engine: FeatureWindowEngine,
        repository: FeatureRepository,
        state: OnlineStateStore,
        publisher: CanonicalEventPublisher,
    ) -> None:
        self._engine = engine
        self._repository = repository
        self._state = state
        self._publisher = publisher

    async def process(self, signal: FeatureSignal) -> list[FeatureSnapshot]:
        snapshots = self._engine.ingest(signal)
        for snapshot in snapshots:
            await self._repository.persist(snapshot)
            await self._state.set_json(
                f"latest:features:{snapshot.scope_id}:{snapshot.asset_id}:"
                f"{snapshot.interval_seconds}",
                snapshot.model_dump(mode="json"),
            )
            await self._state.set_json(
                f"latest:features:{snapshot.asset_id}:{snapshot.interval_seconds}",
                snapshot.model_dump(mode="json"),
            )
            event = CanonicalEvent(
                event_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"feature-event:{snapshot.scope_id}:{snapshot.feature_window_id}:"
                        f"{snapshot.revision}",
                    )
                ),
                event_type=(
                    EventType.feature_window_finalized
                    if snapshot.is_final
                    else EventType.feature_window_updated
                ),
                schema_version=1,
                source="feature-window-engine-v1",
                source_event_id=(
                    f"{snapshot.scope_id}:{snapshot.feature_window_id}:{snapshot.revision}"
                ),
                asset_id=snapshot.asset_id,
                event_time=snapshot.window_end,
                ingested_at=signal.ingested_at,
                processed_at=datetime.now(tz=UTC),
                partition_key=snapshot.asset_id,
                replay=ReplayMetadata(
                    is_replay=snapshot.scope_id != "LIVE",
                    replay_session_id=(snapshot.scope_id if snapshot.scope_id != "LIVE" else None),
                ),
                trace=TraceMetadata(causation_id=signal.event_id),
                payload=snapshot.model_dump(mode="json"),
            )
            is_market_signal = signal.kind in {
                SignalKind.market_trade,
                SignalKind.market_candle,
                SignalKind.orderbook,
            } or (
                signal.kind == SignalKind.data_quality and signal.values.get("domain") == "market"
            )
            topic = "features.market.v1" if is_market_signal else "features.social.v1"
            await self._publisher.publish(topic, event)
        return snapshots


class InMemoryFeatureRepository:
    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, int], FeatureSnapshot] = {}
        self.history: list[FeatureSnapshot] = []

    async def persist(self, snapshot: FeatureSnapshot) -> bool:
        identity = (str(snapshot.feature_window_id), snapshot.revision)
        if identity in self.snapshots:
            return False
        self.snapshots[identity] = snapshot
        self.history.append(snapshot)
        return True
