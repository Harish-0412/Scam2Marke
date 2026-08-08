# First Demo Scenario

## Scenario

Replay a synthetic or historical low-liquidity asset scenario where a coordinated social narrative appears before abnormal market volume and price movement.

## Required Timeline

1. Baseline market and social activity remains normal.
2. Social mention velocity rises.
3. Multiple pseudonymous actors repeat similar language/URLs/hashtags.
4. Asset resolver maps posts to the target asset with confidence.
5. Market volume becomes abnormal.
6. Fusion score crosses `WATCH`.
7. Coordination/narrative evidence strengthens the campaign.
8. Fusion score crosses `HIGH`.
9. Alert is emitted through WebSocket/SSE.
10. Analyst opens the alert and sees evidence, timeline, and lead time.

## Dataset Decision For First Build

Use synthetic generated replay data for the first working demo.

Reason:

- it avoids dependency on fragile external data access during the first backend build;
- it lets the team design exact event-time, late-event, duplicate-event, and lead-time cases;
- it creates a deterministic replay fixture for CI and demo regression;
- it can later be swapped for historical crypto market data plus social data without changing the pipeline contract.

Phase 2 should create this source as `synthetic-pump-v1`.

The scenario must include:

- normal baseline period;
- social hype surge before market anomaly;
- duplicate market and social events;
- at least one late event;
- ambiguous symbol mention;
- unsupported narrative claim;
- pump phase;
- dump phase;
- expected detection lead time.
