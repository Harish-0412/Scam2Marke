# Product Scope Reset

The backend plan has been reset from a generic scam marketplace to a pump-and-dump market-surveillance platform.

## Removed Backlog

- marketplace listing CRUD;
- buyer/seller role model;
- checkout;
- Stripe Connect;
- payout logic;
- marketplace reviews;
- buyer/seller messaging;
- marketplace disputes and refunds.

## Retained Engineering Patterns

- modular monolith;
- PostgreSQL;
- Redis;
- event-driven boundaries;
- idempotency;
- transactional outbox where database state emits events;
- audit logs;
- structured observability;
- Docker Compose;
- API versioning;
- correlation IDs;
- human review for high-impact model output.
