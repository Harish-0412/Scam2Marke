import asyncio
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from uuid import NAMESPACE_URL, uuid5

import httpx

from scam2market.common.time import utc_now
from scam2market.ingestion.market import MarketDatum, _datum_id, _event_type
from scam2market.ingestion.social import RawSocialPost
from scam2market.resilience.circuit_breaker import CircuitBreaker
from scam2market.schemas.domain import MarketCandle, MarketTrade, OrderBookUpdate
from scam2market.schemas.events import CanonicalEvent, EventType

HTML_TAG_RE = re.compile(r"<[^>]+>")


class BinanceMarketProvider:
    source = "binance-live-v1"

    def __init__(
        self,
        symbols: Sequence[str],
        *,
        base_url: str = "https://api.binance.com",
        poll_interval_seconds: float = 1.0,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        max_polls: int | None = None,
        clock: Callable[[], datetime] = utc_now,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        if not symbols:
            raise ValueError("at least one Binance symbol is required")
        self._symbols = tuple(symbol.upper() for symbol in symbols)
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(base_url=self._base_url, timeout=10)
        )
        self._max_polls = max_polls
        self._clock = clock
        self._circuit = circuit_breaker or CircuitBreaker(f"binance:{self._base_url}")
        self._last_trade_id: dict[str, int] = {}
        self._last_candle_open: dict[str, int] = {}
        self._emission_sequence: dict[str, int] = {}

    async def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]:
        if replay_session_id is not None:
            raise ValueError("live Binance provider cannot be used for replay")
        poll = 0
        async with self._client_factory() as client:
            while self._max_polls is None or poll < self._max_polls:
                poll += 1
                for symbol in self._symbols:
                    for datum, _ in await self._circuit.call(
                        lambda symbol=symbol: self._fetch_symbol(client, symbol)
                    ):
                        sequence = self._emission_sequence.get(symbol, 0) + 1
                        self._emission_sequence[symbol] = sequence
                        yield _market_event(datum, self.source, sequence, self._clock())
                if self._max_polls is None or poll < self._max_polls:
                    await asyncio.sleep(self._poll_interval)

    async def _fetch_symbol(
        self, client: httpx.AsyncClient, symbol: str
    ) -> list[tuple[MarketDatum, int]]:
        from_id = self._last_trade_id.get(symbol)
        trade_params: dict[str, str | int] = {"symbol": symbol, "limit": 100}
        if from_id is not None:
            trade_params["fromId"] = from_id + 1
        trades_response, depth_response, candles_response = await asyncio.gather(
            client.get("/api/v3/aggTrades", params=trade_params),
            client.get("/api/v3/depth", params={"symbol": symbol, "limit": 5}),
            client.get("/api/v3/klines", params={"symbol": symbol, "interval": "1m", "limit": 2}),
        )
        for response in (trades_response, depth_response, candles_response):
            response.raise_for_status()
        results: list[tuple[MarketDatum, int]] = []
        for raw in trades_response.json():
            trade_id = int(raw["a"])
            if trade_id <= self._last_trade_id.get(symbol, -1):
                continue
            results.append(
                (
                    MarketTrade(
                        trade_id=f"binance:{symbol}:{trade_id}",
                        asset_id=symbol,
                        event_time=_milliseconds(int(raw["T"])),
                        price=float(raw["p"]),
                        quantity=float(raw["q"]),
                        side="SELL" if bool(raw["m"]) else "BUY",
                        source=self.source,
                    ),
                    trade_id,
                )
            )
            self._last_trade_id[symbol] = trade_id
        depth = depth_response.json()
        depth_sequence = int(depth["lastUpdateId"])
        bids = [(float(price), float(quantity)) for price, quantity in depth.get("bids", [])]
        asks = [(float(price), float(quantity)) for price, quantity in depth.get("asks", [])]
        results.append(
            (
                OrderBookUpdate(
                    update_id=f"binance:{symbol}:depth:{depth_sequence}",
                    asset_id=symbol,
                    event_time=self._clock(),
                    best_bid=bids[0][0] if bids else None,
                    best_ask=asks[0][0] if asks else None,
                    bids=bids,
                    asks=asks,
                    source=self.source,
                ),
                depth_sequence,
            )
        )
        candles = candles_response.json()
        for raw in candles[:-1]:
            open_time = int(raw[0])
            if open_time <= self._last_candle_open.get(symbol, -1):
                continue
            results.append(
                (
                    MarketCandle(
                        candle_id=f"binance:{symbol}:1m:{open_time}",
                        asset_id=symbol,
                        event_time=_milliseconds(int(raw[6])),
                        interval_seconds=60,
                        open=float(raw[1]),
                        high=float(raw[2]),
                        low=float(raw[3]),
                        close=float(raw[4]),
                        volume=float(raw[5]),
                        source=self.source,
                    ),
                    open_time,
                )
            )
            self._last_candle_open[symbol] = open_time
        return sorted(results, key=lambda item: (item[0].event_time, _datum_id(item[0])))


class MastodonSocialProvider:
    source = "mastodon-public-v1"

    def __init__(
        self,
        *,
        base_url: str = "https://mastodon.social",
        poll_interval_seconds: float = 15,
        access_token: str | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        max_polls: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(base_url=self._base_url, timeout=15, headers=headers)
        )
        self._max_polls = max_polls
        self._since_id: str | None = None
        self._sequence = 0

    async def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]:
        if replay_session_id is not None:
            raise ValueError("live Mastodon provider cannot be used for replay")
        poll = 0
        async with self._client_factory() as client:
            while self._max_polls is None or poll < self._max_polls:
                poll += 1
                params: dict[str, str | int] = {"limit": 40}
                if self._since_id:
                    params["since_id"] = self._since_id
                response = await client.get("/api/v1/timelines/public", params=params)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if response.status_code in {401, 422}:
                        raise RuntimeError(
                            "Mastodon instance requires MASTODON_ACCESS_TOKEN for public timeline"
                        ) from exc
                    raise
                statuses = sorted(response.json(), key=lambda item: int(item["id"]))
                for raw in statuses:
                    self._sequence += 1
                    self._since_id = max(self._since_id or "0", str(raw["id"]), key=int)
                    post = RawSocialPost(
                        source_post_id=str(raw["id"]),
                        platform="mastodon",
                        raw_author_id=str(raw["account"]["id"]),
                        event_time=datetime.fromisoformat(
                            str(raw["created_at"]).replace("Z", "+00:00")
                        ),
                        text=_plain_text(str(raw.get("content", ""))),
                        language=raw.get("language"),
                        reply_to=raw.get("in_reply_to_id"),
                        repost_of=(str(raw["reblog"]["id"]) if raw.get("reblog") else None),
                        engagement={
                            "reblogs": int(raw.get("reblogs_count", 0)),
                            "favourites": int(raw.get("favourites_count", 0)),
                            "replies": int(raw.get("replies_count", 0)),
                        },
                    )
                    yield _social_event(post, self.source, self._sequence)
                if self._max_polls is None or poll < self._max_polls:
                    await asyncio.sleep(self._poll_interval)


class RssSocialProvider:
    source = "rss-live-v1"

    def __init__(
        self,
        urls: Sequence[str],
        *,
        poll_interval_seconds: float = 60,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        max_polls: int | None = None,
    ) -> None:
        if not urls:
            raise ValueError("at least one RSS URL is required")
        self._urls = tuple(urls)
        self._poll_interval = poll_interval_seconds
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=15))
        self._max_polls = max_polls
        self._seen: set[str] = set()

    async def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]:
        if replay_session_id is not None:
            raise ValueError("live RSS provider cannot be used for replay")
        poll = 0
        async with self._client_factory() as client:
            while self._max_polls is None or poll < self._max_polls:
                poll += 1
                for url in self._urls:
                    response = await client.get(url)
                    response.raise_for_status()
                    for post in _parse_rss(response.content, url):
                        if post.source_post_id in self._seen:
                            continue
                        self._seen.add(post.source_post_id)
                        sequence = int(
                            hashlib.sha256(post.source_post_id.encode()).hexdigest()[:12], 16
                        )
                        yield _social_event(post, self.source, sequence)
                if self._max_polls is None or poll < self._max_polls:
                    await asyncio.sleep(self._poll_interval)


def _market_event(
    datum: MarketDatum, source: str, sequence: int, ingested_at: datetime
) -> CanonicalEvent:
    source_event_id = _datum_id(datum)
    event_id = str(uuid5(NAMESPACE_URL, f"{source}:{source_event_id}"))
    return CanonicalEvent(
        event_id=event_id,
        origin_event_id=f"{source}:{source_event_id}",
        delivery_event_id=event_id,
        event_type=_event_type(datum),
        schema_version=1,
        source=source,
        source_event_id=source_event_id,
        source_sequence=sequence,
        asset_id=datum.asset_id,
        event_time=datum.event_time,
        ingested_at=ingested_at,
        partition_key=datum.asset_id,
        payload=datum.model_dump(mode="json"),
    )


def _social_event(post: RawSocialPost, source: str, sequence: int) -> CanonicalEvent:
    event_id = str(uuid5(NAMESPACE_URL, f"{source}:{post.source_post_id}"))
    return CanonicalEvent(
        event_id=event_id,
        origin_event_id=f"{source}:{post.source_post_id}",
        delivery_event_id=event_id,
        event_type=EventType.social_post_received,
        schema_version=1,
        source=source,
        source_event_id=post.source_post_id,
        source_sequence=sequence,
        event_time=post.event_time,
        ingested_at=utc_now(),
        partition_key=post.platform,
        payload=post.model_dump(mode="json"),
    )


def _parse_rss(payload: bytes, url: str) -> list[RawSocialPost]:
    root = ET.fromstring(payload)
    posts: list[RawSocialPost] = []
    for item in root.findall(".//item"):
        link = item.findtext("link") or ""
        guid = item.findtext("guid") or link or item.findtext("title") or ""
        published = item.findtext("pubDate")
        event_time = parsedate_to_datetime(published).astimezone(UTC) if published else utc_now()
        title = item.findtext("title") or ""
        description = item.findtext("description") or ""
        posts.append(
            RawSocialPost(
                source_post_id=hashlib.sha256(f"{url}:{guid}".encode()).hexdigest(),
                platform="rss",
                raw_author_id=url,
                event_time=event_time,
                text=_plain_text(f"{title} {description} {link}"),
            )
        )
    return sorted(posts, key=lambda post: (post.event_time, post.source_post_id))


def _milliseconds(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(HTML_TAG_RE.sub(" ", value)).split())
