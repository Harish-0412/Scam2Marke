from datetime import UTC, datetime, timedelta

import httpx
import orjson
import pytest

from scam2market.features.engine import FeatureWindowEngine
from scam2market.features.schemas import FeatureSignal, SignalKind, SourceDomain
from scam2market.ingestion.live_providers import (
    BinanceMarketProvider,
    MastodonSocialProvider,
    RssSocialProvider,
)
from scam2market.schemas.events import EventType

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _client_factory(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://provider.test")


@pytest.mark.asyncio
async def test_binance_provider_normalizes_trade_depth_and_closed_candle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("aggTrades"):
            return httpx.Response(
                200,
                json=[{"a": 41, "p": "102.5", "q": "3.2", "T": 1786528800000, "m": False}],
            )
        if request.url.path.endswith("depth"):
            return httpx.Response(
                200,
                json={
                    "lastUpdateId": 900,
                    "bids": [["102.4", "4"], ["102.3", "5"]],
                    "asks": [["102.6", "2"], ["102.7", "3"]],
                },
            )
        return httpx.Response(
            200,
            json=[
                [1786528740000, "100", "103", "99", "102", "50", 1786528799999],
                [1786528800000, "102", "104", "101", "103", "10", 1786528859999],
            ],
        )

    transport = httpx.MockTransport(handler)
    provider = BinanceMarketProvider(
        ["BTCUSDT"],
        client_factory=lambda: _client_factory(transport),
        max_polls=1,
        clock=lambda: NOW,
    )
    events = [event async for event in provider.stream()]
    assert {event.event_type for event in events} == {
        EventType.market_trade_received,
        EventType.market_orderbook_updated,
        EventType.market_candle_closed,
    }
    trade = next(event for event in events if event.event_type == EventType.market_trade_received)
    assert trade.asset_id == "BTCUSDT"
    assert trade.payload["side"] == "BUY"
    book = next(event for event in events if event.event_type == EventType.market_orderbook_updated)
    assert book.payload["bids"][0] == [102.4, 4.0]


@pytest.mark.asyncio
async def test_mastodon_provider_tracks_since_id_and_strips_html() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "501",
                        "created_at": "2026-08-12T10:00:00Z",
                        "content": "<p>$BTC is <strong>moving</strong></p>",
                        "language": "en",
                        "account": {"id": "raw-account"},
                        "in_reply_to_id": None,
                        "reblog": None,
                        "reblogs_count": 2,
                        "favourites_count": 4,
                        "replies_count": 1,
                    }
                ],
            )
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    provider = MastodonSocialProvider(
        client_factory=lambda: _client_factory(transport), max_polls=2, poll_interval_seconds=0
    )
    events = [event async for event in provider.stream()]
    assert len(events) == 1
    assert events[0].payload["text"] == "$BTC is moving"
    assert requests[1].url.params["since_id"] == "501"


@pytest.mark.asyncio
async def test_rss_provider_deduplicates_across_polls() -> None:
    xml = b"""<rss><channel><item><guid>story-1</guid><title>$ETH update</title>
    <description>Trading activity</description><link>https://news.test/1</link>
    <pubDate>Wed, 12 Aug 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=xml))
    provider = RssSocialProvider(
        ["https://news.test/feed"],
        client_factory=lambda: _client_factory(transport),
        max_polls=2,
        poll_interval_seconds=0,
    )
    events = [event async for event in provider.stream()]
    assert len(events) == 1
    assert events[0].payload["platform"] == "rss"


def test_feature_engine_checkpoint_restores_exact_revision_state() -> None:
    engine = FeatureWindowEngine(required_domains=(SourceDomain.market,))
    signals = [
        FeatureSignal(
            event_id=f"event-{index}",
            asset_id="BTCUSDT",
            event_time=NOW + timedelta(seconds=seconds),
            ingested_at=NOW + timedelta(seconds=index),
            kind=SignalKind.market_trade,
            source_domain=SourceDomain.market,
            values={"price": 100 + index, "quantity": 2},
        )
        for index, seconds in enumerate((60, 180, 90))
    ]
    for signal in signals:
        engine.ingest(signal)
    state = engine.export_state()
    encoded = orjson.dumps(state, option=orjson.OPT_SORT_KEYS)

    restored = FeatureWindowEngine(required_domains=(SourceDomain.market,))
    assert restored.restore_state(orjson.loads(encoded)) == 3
    assert restored.export_state() == state
    original = engine.latest("BTCUSDT", 60)
    recovered = restored.latest("BTCUSDT", 60)
    assert original is not None and recovered is not None
    assert recovered.model_dump() == original.model_dump()
    assert restored.ingest(signals[-1]) == []
