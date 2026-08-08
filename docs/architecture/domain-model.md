# Scam2Market Backend Domain Model

Scam2Market is a pump-and-dump intelligence backend, not a marketplace backend. The core domain model is organized around event-time market surveillance, social manipulation detection, graph coordination, campaign lifecycle, alert evidence, replay, and analyst investigation.

## Core Objects

| Object | Purpose |
|---|---|
| `Asset` | Canonical traded instrument being monitored. |
| `MarketTrade` | Normalized trade event with event-time semantics. |
| `MarketCandle` | Normalized OHLCV candle event. |
| `OrderBookUpdate` | Normalized market microstructure snapshot/update. |
| `SocialPost` | Pseudonymized social/information event. |
| `AssetMention` | Confidence-scored mapping from social text to an asset. |
| `Disclosure` | Official disclosure, announcement, or trusted reference document. |
| `FeatureWindow` | Revisioned rolling feature snapshot for a time window. |
| `Narrative` | Cluster of semantically related social posts/claims. |
| `GraphSnapshot` | Graph projection/features for coordination evidence. |
| `ModelScore` | Versioned model output tied to feature inputs. |
| `Campaign` | Persistent suspected manipulation lifecycle for an asset. |
| `Alert` | Analyst-facing warning produced from campaign state and evidence. |
| `EvidenceSnapshot` | Immutable or revisioned evidence backing an alert. |
| `Investigation` | Analyst workflow for review and feedback. |
| `ReplaySession` | Deterministic historical scenario execution context. |

## Explicitly Out Of Core Scope

- buyer/seller marketplace;
- listings;
- checkout and Stripe Connect;
- commissions and payouts;
- reviews;
- buyer/seller messaging;
- marketplace disputes.
