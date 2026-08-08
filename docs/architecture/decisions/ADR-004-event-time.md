# ADR-004: Treat Event Time As A First-Class Contract

## Context

Pump-and-dump detection depends on correct social-to-market lead/lag. Ingestion time or processing time can distort causality.

## Decision

Every canonical event stores event time, ingestion time, and processing time separately. Feature windows are computed by event time and support late-event revisions.

## Alternatives

- Compute by ingestion time.
- Compute by processing time.

## Consequences

This adds complexity but prevents false lead-time claims and makes replay/evaluation defensible.
