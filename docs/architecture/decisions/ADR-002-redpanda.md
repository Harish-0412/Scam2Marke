# ADR-002: Use Redpanda For Event Streaming

## Context

The backend needs durable event logs, consumer groups, replay, partitioning by asset, and Kafka-compatible tooling.

## Decision

Use Redpanda as the streaming broker for market, social, feature, model, campaign, alert, and dead-letter topics.

## Alternatives

- Redis Streams for a simpler MVP.
- Kafka cluster.

## Consequences

Redpanda gives Kafka-compatible semantics with a simpler local demo footprint. Redis remains useful for dedupe, cache, and online state.
