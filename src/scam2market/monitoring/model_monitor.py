import logging
import random
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, start_http_server
from pydantic import BaseModel

logger = logging.getLogger(__name__)
app = FastAPI()

model_prediction_counter = Counter("model_predictions_total", "Total model predictions")
model_drift_gauge = Gauge("model_drift_score", "Current drift score")
model_latency_gauge = Gauge("model_latency_seconds", "Model inference latency")


class DriftReport(BaseModel):
    timestamp: datetime
    drift_score: float
    details: dict[str, Any]


_drift_events: dict[str, DriftReport] = {}
_metrics_started = False


@app.on_event("startup")
async def start_metrics_exporter() -> None:
    global _metrics_started
    if _metrics_started:
        return
    try:
        start_http_server(8001)
        _metrics_started = True
    except OSError as error:
        logger.warning("prometheus_exporter_start_failed", extra={"error": repr(error)})


@app.post("/v1/model/track_prediction")
async def track_prediction() -> dict[str, str | float]:
    model_prediction_counter.inc()
    latency = random.uniform(0.05, 0.2)
    model_latency_gauge.set(latency)
    return {"status": "tracked", "latency": latency}


@app.post("/v1/model/report_drift", response_model=DriftReport)
async def report_drift(drift_score: float, details: dict[str, Any] | None = None) -> DriftReport:
    if drift_score < 0:
        raise HTTPException(status_code=400, detail="Drift score must be non-negative")
    model_drift_gauge.set(drift_score)
    report = DriftReport(
        timestamp=datetime.now(tz=UTC),
        drift_score=drift_score,
        details=details or {},
    )
    _drift_events[report.timestamp.isoformat()] = report
    return report


@app.get("/v1/model/drift_events")
async def get_drift_events() -> list[DriftReport]:
    return list(_drift_events.values())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
