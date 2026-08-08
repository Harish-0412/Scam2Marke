# ADR-001: Use Python And FastAPI For The Backend

## Context

Scam2Market is dominated by time-series features, ML inference, NLP embeddings, graph analytics, replay evaluation, and model tracking.

## Decision

Use Python 3.12+ and FastAPI for the API and worker codebase.

## Alternatives

- Node.js/NestJS API plus Python ML services.
- Java/Kotlin streaming service.

## Consequences

Python keeps ML/data processing close to the API and workers during the hackathon. FastAPI provides typed request/response contracts and async I/O without forcing a microservice split.
