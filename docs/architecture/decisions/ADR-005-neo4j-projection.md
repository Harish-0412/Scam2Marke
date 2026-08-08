# ADR-005: Use Neo4j As A Graph Projection

## Context

Coordination detection benefits from graph relationships between actors, posts, URLs, narratives, assets, campaigns, and alerts.

## Decision

Use Neo4j as a graph projection, not the primary source of truth.

## Alternatives

- Store graph only in PostgreSQL.
- Make Neo4j the source of truth.

## Consequences

PostgreSQL remains authoritative. Neo4j can be rebuilt from normalized events and is allowed to lag or fail without breaking baseline detection.
