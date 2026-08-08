INITIAL_TOPICS: list[str] = [
    "market.trades.v1",
    "market.candles.v1",
    "market.orderbook.v1",
    "social.posts.raw.v1",
    "social.posts.normalized.v1",
    "social.mentions.v1",
    "disclosures.documents.v1",
    "features.market.v1",
    "features.social.v1",
    "model.fusion.score.v1",
    "campaign.events.v1",
    "alerts.events.v1",
    "deadletter.ingestion.v1",
    "deadletter.inference.v1",
]


TOPIC_PARTITIONS: dict[str, int] = {
    "market.trades.v1": 6,
    "market.candles.v1": 6,
    "market.orderbook.v1": 6,
    "social.posts.raw.v1": 6,
    "social.posts.normalized.v1": 6,
    "social.mentions.v1": 6,
}
