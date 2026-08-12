# Checkpoint 4: Calibration, Promotion, And False Positives

This checkpoint turns analyst outcomes into reproducible model-governance inputs.

## Labeled Calibration

Labels are tenant scoped and attached to a model family/version, raw score, event time, explicit
calibration or holdout partition, and optional market segment. Platt scaling is deterministic over
the same label set and records a SHA-256 data hash, coefficients, sample coverage, Brier score, log
loss, expected calibration error, and AUC. Fits reject one-class or undersized datasets.

## Promotion Governance

Candidate promotion fails closed. A candidate must have an active calibration, minimum label
coverage, acceptable holdout ECE and AUC, no latest `DRIFTED` state, and no breach of its rolling
false-positive budget. Each decision persists every check and an audit event. Passing evaluation can
remain `APPROVED` for review or atomically move the `CHAMPION` alias when explicitly requested.

## False-Positive Feedback

Analysts can report legitimate events, asset ambiguity, data-quality failures, low thresholds,
duplicate campaigns, and other causes. Reports are tenant isolated and become an input to promotion
gates instead of disappearing into free-form investigation notes.
