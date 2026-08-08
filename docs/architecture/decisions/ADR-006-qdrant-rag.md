# ADR-006: Use Qdrant For Narrative And Disclosure Retrieval

## Context

The backend needs semantic retrieval for narratives and time-bounded claim verification.

## Decision

Use Qdrant for embeddings and filtered retrieval by asset, source, and event-time constraints.

## Alternatives

- PostgreSQL pgvector.
- OpenSearch vector search.

## Consequences

Qdrant provides a focused vector store. Retrieval must always enforce time bounds to avoid leaking future information into past alert explanations.
