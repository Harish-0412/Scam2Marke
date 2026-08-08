# Scam2Market Service Map

The hackathon backend is a modular monolith plus worker processes. Services share schemas and storage contracts, but each process owns a clear responsibility.

```mermaid
flowchart LR
  API["FastAPI API"] --> PG[("PostgreSQL / TimescaleDB")]
  API --> Redis[("Redis")]
  API --> Neo4j[("Neo4j")]
  API --> Qdrant[("Qdrant")]

  Market["Market Ingestor"] --> Redpanda[("Redpanda")]
  Social["Social Ingestor"] --> Redpanda
  Replay["Replay Scheduler"] --> Redpanda

  Redpanda --> Stream["Stream Worker"]
  Stream --> PG
  Stream --> Redis

  Stream --> Intel["Intelligence Worker"]
  Intel --> PG
  Intel --> Redis

  Stream --> Graph["Graph Worker"]
  Graph --> Neo4j
  Graph --> PG

  Stream --> Verify["Verification Worker"]
  Verify --> Qdrant
  Verify --> PG

  Intel --> Alerts["Campaign / Alert Events"]
  Alerts --> API
```

## Process Responsibilities

| Process | Responsibility |
|---|---|
| API | Control plane, dashboard REST endpoints, WebSocket/SSE, health/config. |
| Market Ingestor | Live/replayed market adapters, normalization, event publication. |
| Social Ingestor | Social replay/adapters, normalization, asset mention extraction. |
| Stream Worker | Deduplication, event-time assignment, persistence, feature-window updates. |
| Intelligence Worker | Baseline detectors, fusion, campaign and alert state. |
| Graph Worker | Neo4j projection and graph features. |
| Verification Worker | Time-bounded disclosure/claim verification. |
| Replay Scheduler | Virtual-clock replay and scenario isolation. |
