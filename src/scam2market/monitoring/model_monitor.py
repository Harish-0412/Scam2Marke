from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import datetime
import random
from typing import Dict, Any
from prometheus_client import Counter, Gauge, start_http_server

app = FastAPI()

# Prometheus metrics
model_prediction_counter = Counter("model_predictions_total", "Total number of model predictions")
model_drift_gauge = Gauge("model_drift_score", "Current drift score (KL divergence)")
model_latency_gauge = Gauge("model_latency_seconds", "Latency of model inference")

# In‑memory store for drift events (for demo)
_drift_events: Dict[str, Any] = {}


class DriftReport(BaseModel):
    timestamp: datetime.datetime
    drift_score: float
    details: Dict[str, Any]


@app.post("/v1/model/track_prediction")
async def track_prediction():
    # Dummy endpoint to be called after each model prediction
    model_prediction_counter.inc()
    # Simulate latency measurement
    latency = random.uniform(0.05, 0.2)
    model_latency_gauge.set(latency)
    return {"status": "tracked", "latency": latency}


@app.post("/v1/model/report_drift", response_model=DriftReport)
async def report_drift(drift_score: float, details: Dict[str, Any] = {}):
    if drift_score < 0:
        raise HTTPException(status_code=400, detail="Drift score must be non‑negative")
    model_drift_gauge.set(drift_score)
    report = DriftReport(
        timestamp=datetime.datetime.utcnow(), drift_score=drift_score, details=details
    )
    _drift_events[report.timestamp.isoformat()] = report
    return report


@app.get("/v1/model/drift_events")
async def get_drift_events():
    return list(_drift_events.values())


@app.get("/health")
async def health():
    return {"status": "ok"}


# Start Prometheus exporter on a separate thread (port 8001)
import threading

threading.Thread(target=start_http_server, args=(8001,), daemon=True).start()
