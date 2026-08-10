from dataclasses import dataclass
from enum import StrEnum

from scam2market.features.schemas import FeatureSnapshot


def _number(features: dict[str, float | int | None], name: str) -> float:
    value = features.get(name)
    return float(value) if value is not None else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class MissingReason(StrEnum):
    source_unavailable = "SOURCE_UNAVAILABLE"
    source_idle = "SOURCE_IDLE"
    source_degraded = "SOURCE_DEGRADED"
    insufficient_history = "INSUFFICIENT_HISTORY"
    no_observations = "NO_OBSERVATIONS"
    not_provided = "NOT_PROVIDED"
    invalid_orderbook = "INVALID_ORDERBOOK"
    insufficient_peer_data = "INSUFFICIENT_PEER_DATA"
    not_ready = "NOT_READY"
    qdrant_degraded = "QDRANT_DEGRADED"
    neo4j_degraded = "NEO4J_DEGRADED"
    no_narrative = "NO_NARRATIVE"
    no_claim = "NO_CLAIM"
    insufficient_graph = "INSUFFICIENT_GRAPH"
    verification_unknown = "VERIFICATION_UNKNOWN"
    timeout = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class DetectorOutput:
    name: str
    score: float | None
    model_version: str
    reason: str
    missing_reason: MissingReason | None = None

    @property
    def available(self) -> bool:
        return self.score is not None


class MarketAnomalyDetector:
    version = "market-grouped-baseline-v2"

    def score(self, snapshot: FeatureSnapshot) -> DetectorOutput:
        features = snapshot.features
        has_market = _number(features, "trade_count") > 0 or _number(features, "volume") > 0
        if not has_market:
            missing_reason = (
                MissingReason.source_degraded
                if _number(features, "market_source_degraded") > 0
                else MissingReason.source_unavailable
            )
            return DetectorOutput(
                "market_score",
                None,
                self.version,
                "market features unavailable",
                missing_reason,
            )

        groups: list[tuple[str, float, float]] = [
            (
                "direction",
                _clamp(abs(_number(features, "price_return")) / 0.10),
                0.30,
            ),
            (
                "activity",
                0.70 * _clamp((_number(features, "relative_volume") - 1.0) / 4.0)
                + 0.30 * _clamp(_number(features, "trade_count") / 30.0),
                0.35,
            ),
            ("stress", _clamp(_number(features, "volatility") / 0.05), 0.20),
        ]
        book_valid = features.get("orderbook_valid") == 1
        if book_valid:
            groups.append(
                (
                    "microstructure",
                    0.65 * _clamp(abs(_number(features, "orderbook_imbalance")))
                    + 0.35 * _clamp(_number(features, "spread") / 0.02),
                    0.15,
                )
            )
        available_weight = sum(weight for _, _, weight in groups)
        score = sum(value * weight for _, value, weight in groups) / available_weight
        reason = "grouped market anomaly blend: " + ", ".join(name for name, _, _ in groups)
        if not book_valid:
            reason += "; invalid or unavailable orderbook excluded"
        return DetectorOutput("market_score", _clamp(score), self.version, reason)


class SocialSurgeDetector:
    version = "social-baseline-v1"

    def score(self, snapshot: FeatureSnapshot) -> DetectorOutput:
        features = snapshot.features
        mention_value = features.get("mention_count")
        author_value = features.get("unique_author_count")
        mentions = _number(features, "mention_count")
        authors = _number(features, "unique_author_count")
        hashtag_velocity = _number(features, "hashtag_velocity")
        if mention_value is None and author_value is None:
            if _number(features, "social_source_idle") > 0:
                missing_reason = MissingReason.source_idle
            elif _number(features, "social_source_degraded") > 0:
                missing_reason = MissingReason.source_degraded
            else:
                missing_reason = MissingReason.source_unavailable
            return DetectorOutput(
                "social_score",
                None,
                self.version,
                "social features unavailable",
                missing_reason,
            )
        mention_component = _clamp(mentions / 12.0)
        author_component = _clamp(authors / 8.0)
        velocity_component = _clamp(hashtag_velocity / 10.0)
        new_author_component = _clamp(_number(features, "new_author_ratio"))
        score = (
            0.40 * mention_component
            + 0.25 * author_component
            + 0.20 * velocity_component
            + 0.15 * new_author_component
        )
        return DetectorOutput("social_score", _clamp(score), self.version, "social surge blend")


class CoordinationHeuristicDetector:
    version = "coordination-heuristics-v1"

    def score(self, snapshot: FeatureSnapshot) -> DetectorOutput:
        features = snapshot.features
        if features.get("mention_count") is None:
            return DetectorOutput(
                "coordination_score",
                None,
                self.version,
                "coordination evidence unavailable",
                MissingReason.source_unavailable,
            )
        author_concentration = _number(features, "author_concentration")
        repost_ratio = _number(features, "repost_reply_ratio")
        url_concentration = _number(features, "url_concentration")
        score = 0.40 * author_concentration + 0.35 * repost_ratio + 0.25 * url_concentration
        return DetectorOutput(
            "coordination_score", _clamp(score), self.version, "coordination heuristics"
        )


class TemporalLeadLagDetector:
    version = "temporal-lead-lag-v1"

    def score(self, snapshot: FeatureSnapshot) -> DetectorOutput:
        lead = snapshot.features.get("social_lead_seconds")
        if lead is None:
            return DetectorOutput(
                "temporal_score",
                None,
                self.version,
                "paired streams unavailable",
                MissingReason.source_unavailable,
            )
        lead_seconds = float(lead)
        if lead_seconds <= 0:
            return DetectorOutput("temporal_score", 0.0, self.version, "social did not lead market")
        score = _clamp(lead_seconds / 300.0)
        return DetectorOutput("temporal_score", score, self.version, "social activity led market")


class MarketRegime(StrEnum):
    calm = "CALM"
    trending = "TRENDING"
    volatile = "VOLATILE"
    dislocated = "DISLOCATED"


class MarketRegimeEngine:
    version = "market-regime-v1"

    def classify(self, snapshot: FeatureSnapshot) -> tuple[MarketRegime, float]:
        price_return = abs(_number(snapshot.features, "price_return"))
        volatility = _number(snapshot.features, "volatility")
        if price_return >= 0.20 or volatility >= 0.10:
            return MarketRegime.dislocated, _clamp(max(price_return / 0.4, volatility / 0.2))
        if volatility >= 0.04:
            return MarketRegime.volatile, _clamp(volatility / 0.10)
        if price_return >= 0.05:
            return MarketRegime.trending, _clamp(price_return / 0.20)
        return MarketRegime.calm, _clamp(1.0 - max(price_return / 0.05, volatility / 0.04))


class LiquidityClass(StrEnum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"
    unknown = "UNKNOWN"


class LiquidityClassifier:
    version = "liquidity-class-v1"

    def classify(self, snapshot: FeatureSnapshot) -> tuple[LiquidityClass, float]:
        volume = _number(snapshot.features, "volume")
        depth = _number(snapshot.features, "top_n_depth")
        if volume <= 0 and depth <= 0:
            return LiquidityClass.unknown, 0.0
        liquidity = volume + depth
        if liquidity < 10_000:
            return LiquidityClass.low, _clamp(1.0 - liquidity / 10_000)
        if liquidity < 250_000:
            return LiquidityClass.medium, _clamp(liquidity / 250_000)
        return LiquidityClass.high, _clamp(liquidity / 1_000_000)


class CrossAssetContextBaseline:
    version = "cross-asset-context-v1"

    def relative_score(
        self, snapshot: FeatureSnapshot, peer_returns: list[float]
    ) -> DetectorOutput:
        if len(peer_returns) < 3:
            return DetectorOutput(
                "cross_asset_score",
                None,
                self.version,
                "insufficient peer observations",
                MissingReason.insufficient_peer_data,
            )
        mean = sum(peer_returns) / len(peer_returns)
        variance = sum((value - mean) ** 2 for value in peer_returns) / len(peer_returns)
        if variance <= 0:
            return DetectorOutput("cross_asset_score", 0.0, self.version, "peers have no variance")
        z_score = abs((_number(snapshot.features, "price_return") - mean) / variance**0.5)
        return DetectorOutput(
            "cross_asset_score", _clamp(z_score / 4.0), self.version, "peer-relative return"
        )
