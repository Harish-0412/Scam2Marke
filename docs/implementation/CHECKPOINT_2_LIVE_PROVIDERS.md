# Checkpoint 2: Live Providers And Durable Feature Checkpoints

## Live Market Provider

`BinanceMarketProvider` polls the public Spot API concurrently for aggregate trades, top-five order
book state, and one-minute candles. It advances aggregate trade IDs, suppresses duplicate candles by
open time, preserves exchange event time, maps aggressor side from the buyer-maker flag, and emits
canonical partitioned events. No exchange credentials are required for these public endpoints.

Provider behavior follows the official
[Binance Spot market-data API](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market).

## Live Social Providers

`MastodonSocialProvider` polls the federated public timeline with a `since_id` cursor, converts HTML
status content to normalized plain text, and preserves reply, repost, language, and engagement data.
An optional access token supports instances where public preview is disabled. See the official
[Mastodon timeline API](https://docs.joinmastodon.org/methods/timelines/).
As of this implementation, `mastodon.social` requires authentication for this route; production
configuration therefore supplies `MASTODON_ACCESS_TOKEN` through the secret store.

`RssSocialProvider` provides a credential-free connector for official news and community feeds. It
normalizes RSS items, parses RFC 2822 timestamps, creates stable feed-scoped IDs, and deduplicates
items across polls.

## Recovery Contract

The feature worker now persists:

- consumer group, topic, partition, and durable Kafka offset;
- feature engine state version;
- ordered canonical signal log;
- SHA-256 state checksum;
- latest source event time and checkpoint update time.

The database checkpoint is written before the Kafka offset is committed. A crash before Kafka
commit replays the record, while the restored event-ID set removes the duplicate. Restoring the
ordered signal log reproduces late-event revision numbers, source watermarks, author-first-seen
state, and finalized windows exactly. A checksum mismatch fails worker startup instead of silently
continuing from corrupt state.

Operators can inspect offset and state metadata through
`GET /api/v1/operations/worker-checkpoints`; checkpoint payloads are intentionally not returned.

## Configuration

Use the `live` Compose profile and configure:

```dotenv
MARKET_PROVIDER=binance
LIVE_MARKET_SYMBOLS=BTCUSDT,ETHUSDT
SOCIAL_PROVIDER=mastodon
MASTODON_BASE_URL=https://mastodon.social
MASTODON_ACCESS_TOKEN=
```

For RSS, set `SOCIAL_PROVIDER=rss` and provide comma-separated `SOCIAL_RSS_URLS`. Synthetic remains
the default so local and CI replays are isolated from network availability.
