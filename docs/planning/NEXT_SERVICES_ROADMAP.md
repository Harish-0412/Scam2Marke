# Next Services Roadmap

## Immediate: Operate Phase 8

The deterministic claim-verification engine exists, but production evidence acquisition is the most
important incomplete product capability.

1. Add official exchange-announcement, regulator-disclosure, project-blog, and reliable-news
   connectors.
2. Add a versioned source-trust and source-policy administration service.
3. Add analyst claim, retrieval, timeline, conflict, and supporting-document views.
4. Add connector rate limits, retention/licensing controls, temporal-leakage tests, and source outage
   fallbacks.
5. Add evidence-bounded LLM summaries only after deterministic verification is complete.

## Production Launch Track

### P0: Identity And Tenant Security

- OpenID Connect or SAML login;
- role-based access for analysts, reviewers, administrators, and service accounts;
- tenant/scope isolation at query and database-policy layers;
- API-key rotation, session revocation, and sensitive-access audit exports.

### P0: Live Data And Data Contracts

- live exchange market/order-book connectors with reconnect and sequence recovery;
- licensed social/news connectors with deletion and retention handling;
- schema registry compatibility enforcement and quarantine topics;
- durable feature-worker checkpoints instead of long-history rebuilds.

### P0: Hosted Staging And Disaster Recovery

- infrastructure as code for networking, compute, managed PostgreSQL, Redis, streaming, and storage;
- private service networking, TLS gateway, managed secrets, and workload identity;
- encrypted backups, restore drills, point-in-time recovery, and regional recovery objectives;
- staging replay gates followed by controlled production promotion.

## Analyst And Product Services

### P1: Investigation Workspace

- alert queues, ownership, saved filters, bulk triage, notes, and evidence comparison;
- campaign timeline and graph exploration;
- claim/disclosure document viewer with event-time cutoff indicators;
- case export to signed PDF/JSON evidence packages.

### P1: Notification And Integration Hub

- signed outbound webhooks with replay and dead-letter handling;
- Slack, Teams, email, and PagerDuty-style alert destinations;
- per-watchlist thresholds, quiet hours, escalation policies, and delivery audit logs;
- SIEM and case-management integrations using stable event contracts.

### P1: Portfolio And Watchlist Intelligence

- organization watchlists, portfolios, labels, and ownership;
- cross-asset contagion and common-promoter detection;
- liquidity-aware risk limits and market-wide regime context;
- daily and weekly manipulation-risk summaries.

## Intelligence Services

### P1: Model Calibration And Governance

- labeled evaluation sets and hard-negative libraries;
- calibrated risk probabilities and per-liquidity-class thresholds;
- drift alerts, challenger promotion approvals, and automated rollback criteria;
- bias, stability, and false-positive reports by source, asset class, and market regime.

### P2: Entity Resolution And Campaign Memory

- cross-platform actor/entity resolution with privacy controls;
- shared URL, wallet, domain, hashtag, and amplifier infrastructure graphs;
- campaign-family matching against historical evidence;
- wallet-flow or on-chain enrichment where legally and technically appropriate.

### P2: Simulation And Adversarial Testing

- scenario authoring service for pump, dump, organic hype, exchange listing, and news shocks;
- mutation testing for delayed, duplicated, poisoned, and missing streams;
- adversarial narrative and prompt-injection evaluation corpus;
- detection lead-time and operator-workload simulation.

## Platform Services

### P1: Security Supply Chain

- dependency update automation;
- container and dependency vulnerability scanning;
- secret scanning and protected-branch checks;
- signed releases, SBOM policy checks, and image admission verification.

### P1: Reliability And Cost Control

- SLOs for ingestion freshness, alert latency, replay completion, and evidence completeness;
- on-call alerts and runbook links from Grafana;
- topic/storage retention controls and cost dashboards;
- load, soak, failover, and restore tests in scheduled workflows.

## Recommended Order

1. Register approved Phase 8 sources and validate analyst verification evidence in staging.
2. Add identity/RBAC and tenant isolation.
3. Provision protected staging with managed secrets and backups.
4. Add live market/social connectors and durable stream checkpoints.
5. Build the investigation dashboard and notification hub.
6. Calibrate models using labeled data and production feedback.
7. Add cross-campaign entity intelligence and adversarial simulation.
