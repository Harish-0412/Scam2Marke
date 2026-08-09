from collections.abc import Sequence

from scam2market.features.schemas import FeatureSignal, SignalKind, SourceDomain
from scam2market.schemas.domain import (
    AssetMention,
    MarketCandle,
    MarketTrade,
    OrderBookUpdate,
    SocialPost,
)
from scam2market.schemas.events import CanonicalEvent


def market_signal(
    event: CanonicalEvent, datum: MarketTrade | MarketCandle | OrderBookUpdate
) -> FeatureSignal:
    if isinstance(datum, MarketTrade):
        kind = SignalKind.market_trade
        values: dict[str, object] = {
            "price": datum.price,
            "quantity": datum.quantity,
            "side": datum.side,
        }
    elif isinstance(datum, MarketCandle):
        kind = SignalKind.market_candle
        values = {
            "open": datum.open,
            "high": datum.high,
            "low": datum.low,
            "close": datum.close,
            "volume": datum.volume,
        }
    else:
        kind = SignalKind.orderbook
        quality = event.payload.get("_quality", {})
        book_valid = bool(quality.get("book_valid", True))
        bid_depth = datum.top_bid_depth or sum(quantity for _, quantity in datum.bids[:5])
        ask_depth = datum.top_ask_depth or sum(quantity for _, quantity in datum.asks[:5])
        total_depth = bid_depth + ask_depth
        values = {
            "spread": datum.spread if book_valid else None,
            "top_n_depth": (total_depth or None) if book_valid else None,
            "imbalance": ((bid_depth - ask_depth) / total_depth if total_depth else None)
            if book_valid
            else None,
            "book_valid": book_valid,
        }
    return FeatureSignal(
        event_id=event.event_id,
        scope_id=event.replay.replay_session_id or "LIVE",
        asset_id=datum.asset_id,
        event_time=datum.event_time,
        ingested_at=event.ingested_at,
        kind=kind,
        source_domain=SourceDomain.market,
        values=values,
    )


def social_signals(
    event: CanonicalEvent,
    post: SocialPost,
    mentions: Sequence[AssetMention],
) -> list[FeatureSignal]:
    asset_ids = sorted({mention.asset_id for mention in mentions if mention.asset_id is not None})
    signals: list[FeatureSignal] = []
    for asset_id in asset_ids:
        signals.append(
            FeatureSignal(
                event_id=f"{event.event_id}:post:{asset_id}",
                scope_id=event.replay.replay_session_id or "LIVE",
                asset_id=asset_id,
                event_time=post.event_time,
                ingested_at=event.ingested_at,
                kind=SignalKind.social_post,
                source_domain=SourceDomain.social,
                values={
                    "author_id": post.author_id,
                    "hashtags": post.hashtags,
                    "cashtags": post.cashtags,
                    "urls": post.urls,
                    "reply_to": post.reply_to,
                    "repost_of": post.repost_of,
                },
            )
        )
        for index, mention in enumerate(
            (item for item in mentions if item.asset_id == asset_id), start=1
        ):
            signals.append(
                FeatureSignal(
                    event_id=f"{event.event_id}:mention:{asset_id}:{index}",
                    scope_id=event.replay.replay_session_id or "LIVE",
                    asset_id=asset_id,
                    event_time=post.event_time,
                    ingested_at=event.ingested_at,
                    kind=SignalKind.asset_mention,
                    source_domain=SourceDomain.social,
                    values={
                        "confidence": mention.confidence,
                        "resolver_version": mention.resolver_version,
                    },
                )
            )
    return signals
