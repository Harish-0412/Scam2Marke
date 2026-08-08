# ADR-007: Start As A Modular Monolith With Workers

## Context

The project has a short hackathon horizon but production-shaped architecture requirements.

## Decision

Build one shared backend codebase with a FastAPI API and multiple worker entrypoints.

## Alternatives

- Many independent microservices.
- Single API process with all work in request handlers.

## Consequences

The team gets fast iteration and shared contracts while preserving boundaries that can become independent services later.
