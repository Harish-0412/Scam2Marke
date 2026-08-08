# ADR-003: Use PostgreSQL And TimescaleDB

## Context

Scam2Market needs both relational control-plane data and time-series market/feature data.

## Decision

Use PostgreSQL as the system of record and TimescaleDB for high-frequency market and feature-window tables.

## Alternatives

- Plain PostgreSQL only.
- ClickHouse or InfluxDB.

## Consequences

TimescaleDB keeps relational integrity while enabling hypertables and continuous aggregates in later phases.
