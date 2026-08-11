from datetime import UTC, datetime
from typing import Any

import httpx

from scam2market.common.logging import get_logger
from scam2market.evaluation.schemas import ReplayEvaluation

logger = get_logger(__name__)


class MlflowTrackingClient:
    def __init__(self, tracking_uri: str, *, timeout_seconds: float = 2.0) -> None:
        self._tracking_uri = tracking_uri.rstrip("/")
        self._timeout = timeout_seconds

    async def log_evaluation(self, evaluation: ReplayEvaluation) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                experiment_id = await self._experiment_id(client, "Scam2Market Replay Evaluation")
                response = await client.post(
                    f"{self._tracking_uri}/api/2.0/mlflow/runs/create",
                    json={
                        "experiment_id": experiment_id,
                        "tags": [
                            {
                                "key": "replay_session_id",
                                "value": str(evaluation.replay_session_id),
                            },
                            {"key": "manifest_hash", "value": evaluation.manifest_hash},
                            {"key": "evaluation_version", "value": evaluation.evaluation_version},
                        ],
                    },
                )
                response.raise_for_status()
                run_id = str(response.json()["run"]["info"]["run_id"])
                logged = await client.post(
                    f"{self._tracking_uri}/api/2.0/mlflow/runs/log-batch",
                    json={
                        "run_id": run_id,
                        "metrics": _metrics(evaluation),
                        "params": [
                            {"key": "ablation_profiles", "value": str(len(evaluation.ablations))}
                        ],
                    },
                )
                logged.raise_for_status()
                updated = await client.post(
                    f"{self._tracking_uri}/api/2.0/mlflow/runs/update",
                    json={"run_id": run_id, "status": "FINISHED"},
                )
                updated.raise_for_status()
                return run_id
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "mlflow_evaluation_log_failed",
                extra={"error": str(exc), "evaluation_id": str(evaluation.evaluation_id)},
            )
            return None

    async def _experiment_id(self, client: httpx.AsyncClient, name: str) -> str:
        response = await client.get(
            f"{self._tracking_uri}/api/2.0/mlflow/experiments/get-by-name",
            params={"experiment_name": name},
        )
        if response.status_code == 404:
            created = await client.post(
                f"{self._tracking_uri}/api/2.0/mlflow/experiments/create",
                json={"name": name},
            )
            created.raise_for_status()
            return str(created.json()["experiment_id"])
        response.raise_for_status()
        return str(response.json()["experiment"]["experiment_id"])


def _metrics(evaluation: ReplayEvaluation) -> list[dict[str, Any]]:
    timestamp = int(datetime.now(tz=UTC).timestamp() * 1000)
    values: dict[str, float] = {
        "alert_count": float(evaluation.metrics.alert_count),
        "lead_time_seconds": float(evaluation.metrics.lead_time_seconds or 0),
        "hard_negative_precision_proxy": evaluation.metrics.hard_negative_precision_proxy,
        "false_positive_rate": evaluation.metrics.false_positive_rate,
        "p95_latency_ms": evaluation.metrics.p95_latency_ms,
        "peak_score": evaluation.metrics.peak_score,
    }
    values.update(
        {
            f"ablation.{item.profile.lower()}.peak_score": item.metrics.peak_score
            for item in evaluation.ablations
        }
    )
    return [
        {"key": key, "value": value, "timestamp": timestamp, "step": 0}
        for key, value in values.items()
    ]
