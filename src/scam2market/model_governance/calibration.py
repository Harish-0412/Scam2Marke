import hashlib
import math
from dataclasses import dataclass

import orjson


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    sample_count: int
    positive_count: int
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    auc: float


@dataclass(frozen=True, slots=True)
class PlattCalibration:
    slope: float
    intercept: float
    metrics: CalibrationMetrics
    data_hash: str

    def predict(self, score: float) -> float:
        return _sigmoid(self.slope * _logit(score) + self.intercept)


def fit_platt_calibration(
    observations: list[tuple[float, bool]],
    *,
    minimum_samples: int = 20,
    iterations: int = 1500,
    learning_rate: float = 0.05,
) -> PlattCalibration:
    if len(observations) < minimum_samples:
        raise ValueError(f"at least {minimum_samples} labels are required")
    positives = sum(label for _, label in observations)
    if positives == 0 or positives == len(observations):
        raise ValueError("calibration labels must contain both outcomes")
    ordered = sorted((float(score), bool(label)) for score, label in observations)
    slope, intercept = 1.0, 0.0
    for _ in range(iterations):
        slope_gradient = 0.0
        intercept_gradient = 0.0
        for score, label in ordered:
            transformed = _logit(score)
            error = _sigmoid(slope * transformed + intercept) - float(label)
            slope_gradient += error * transformed
            intercept_gradient += error
        scale = 1 / len(ordered)
        slope -= learning_rate * slope_gradient * scale
        intercept -= learning_rate * intercept_gradient * scale
    probabilities = [_sigmoid(slope * _logit(score) + intercept) for score, _ in ordered]
    labels = [label for _, label in ordered]
    return PlattCalibration(
        slope=round(slope, 10),
        intercept=round(intercept, 10),
        metrics=calibration_metrics(probabilities, labels),
        data_hash=hashlib.sha256(orjson.dumps(ordered)).hexdigest(),
    )


def calibration_metrics(
    probabilities: list[float], labels: list[bool], bins: int = 10
) -> CalibrationMetrics:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have equal non-zero length")
    count = len(labels)
    brier = (
        sum((value - float(label)) ** 2 for value, label in zip(probabilities, labels, strict=True))
        / count
    )
    log_loss = (
        -sum(
            float(label) * math.log(_clip(value)) + (1 - float(label)) * math.log(_clip(1 - value))
            for value, label in zip(probabilities, labels, strict=True)
        )
        / count
    )
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [
            item
            for item in zip(probabilities, labels, strict=True)
            if lower <= item[0] < upper or (index == bins - 1 and item[0] == 1)
        ]
        if members:
            confidence = sum(value for value, _ in members) / len(members)
            accuracy = sum(label for _, label in members) / len(members)
            ece += len(members) / count * abs(confidence - accuracy)
    return CalibrationMetrics(
        sample_count=count,
        positive_count=sum(labels),
        brier_score=round(brier, 8),
        log_loss=round(log_loss, 8),
        expected_calibration_error=round(ece, 8),
        auc=round(_auc(probabilities, labels), 8),
    )


def promotion_checks(
    *,
    metrics: dict[str, float],
    sample_count: int,
    minimum_samples: int,
    maximum_ece: float,
    minimum_auc: float,
    drift_status: str | None,
    false_positive_count: int,
    false_positive_budget: int,
    champion_brier_score: float | None = None,
    brier_tolerance: float = 0.0,
    champion_comparison_required: bool = False,
) -> dict[str, bool]:
    return {
        "minimum_samples": sample_count >= minimum_samples,
        "maximum_ece": metrics["expected_calibration_error"] <= maximum_ece,
        "minimum_auc": metrics["auc"] >= minimum_auc,
        "drift_stable": drift_status != "DRIFTED",
        "false_positive_budget": false_positive_count <= false_positive_budget,
        "champion_calibration_available": not champion_comparison_required
        or champion_brier_score is not None,
        "not_worse_than_champion": not champion_comparison_required
        or (
            champion_brier_score is not None
            and metrics["brier_score"] <= champion_brier_score + brier_tolerance
        ),
    }


def _auc(probabilities: list[float], labels: list[bool]) -> float:
    positives = [value for value, label in zip(probabilities, labels, strict=True) if label]
    negatives = [value for value, label in zip(probabilities, labels, strict=True) if not label]
    if not positives or not negatives:
        return 0.5
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _clip(value: float) -> float:
    return min(1 - 1e-9, max(1e-9, value))


def _logit(value: float) -> float:
    clipped = _clip(value)
    return math.log(clipped / (1 - clipped))


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return 1 / (1 + exponent)
    exponent = math.exp(value)
    return exponent / (1 + exponent)
