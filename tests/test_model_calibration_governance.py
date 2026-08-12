from pydantic import ValidationError

from scam2market.api.routes.model_governance import FalsePositiveCreate
from scam2market.model_governance.calibration import (
    calibration_metrics,
    fit_platt_calibration,
    promotion_checks,
)


def test_platt_calibration_is_deterministic_and_improves_overconfident_scores() -> None:
    observations = [
        *((0.35 + index * 0.005, False) for index in range(10)),
        *((0.65 + index * 0.005, True) for index in range(10)),
    ]
    baseline = calibration_metrics(
        [score for score, _ in observations], [label for _, label in observations]
    )
    first = fit_platt_calibration(observations)
    second = fit_platt_calibration(list(reversed(observations)))

    assert first.data_hash == second.data_hash
    assert first.slope == second.slope
    assert first.metrics.brier_score < baseline.brier_score
    assert first.metrics.auc == 1.0


def test_promotion_fails_closed_for_drift_and_false_positive_budget() -> None:
    checks = promotion_checks(
        metrics={"expected_calibration_error": 0.04, "auc": 0.91, "brier_score": 0.11},
        sample_count=100,
        minimum_samples=20,
        maximum_ece=0.12,
        minimum_auc=0.65,
        drift_status="DRIFTED",
        false_positive_count=6,
        false_positive_budget=5,
        champion_brier_score=0.08,
        brier_tolerance=0.01,
        champion_comparison_required=True,
    )
    assert checks["minimum_samples"] is True
    assert checks["drift_stable"] is False
    assert checks["false_positive_budget"] is False
    assert checks["not_worse_than_champion"] is False
    assert not all(checks.values())


def test_false_positive_reports_use_a_bounded_reason_taxonomy() -> None:
    payload: dict[str, object] = {
        "model_family": "fusion",
        "model_version": "v-test",
        "asset_id": "S2MUSDT",
        "reason_code": "LEGITIMATE_EVENT",
        "notes": "An exchange listing announcement explains the activity.",
        "alert_id": None,
    }
    assert FalsePositiveCreate.model_validate(payload).reason_code == "LEGITIMATE_EVENT"
    try:
        FalsePositiveCreate.model_validate({**payload, "reason_code": "UNBOUNDED_FREE_TEXT"})
    except ValidationError:
        pass
    else:
        raise AssertionError("unsupported false-positive reason was accepted")
