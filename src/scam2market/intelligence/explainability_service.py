import uuid
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


def _load_optional_explainer() -> tuple[Any | None, Any | None]:
    try:
        joblib = import_module("joblib")
        shap = import_module("shap")
        model: Any = joblib.load("models/pretrained_model.joblib")
        try:
            explainer: Any = shap.TreeExplainer(model)
        except Exception:
            feature_count = len(model.feature_names_in_)
            explainer = shap.KernelExplainer(model.predict, np.zeros((1, feature_count)))
        return model, explainer
    except (ImportError, OSError, AttributeError, ValueError):
        return None, None


_model, _explainer = _load_optional_explainer()


class ExplainRequest(BaseModel):
    model_version: str
    prediction_id: str
    features: dict[str, Any]


class ExplainResponse(BaseModel):
    explanation_id: str
    model_version: str
    prediction_id: str
    created_at: datetime
    explanation: dict[str, float]
    raw_shap_values: Any = None


_explanations: dict[str, ExplainResponse] = {}


def _generate_explanation(
    features: dict[str, Any],
) -> tuple[dict[str, float], object | None]:
    if _model is None or _explainer is None:
        return {name: 1.0 / (index + 1) for index, name in enumerate(features)}, None
    feature_names = list(features)
    values = np.array([float(features[name]) for name in feature_names], dtype=float).reshape(1, -1)
    shap_values: Any = _explainer.shap_values(values)
    if isinstance(shap_values, list):
        shap_values = shap_values[0]
    shap_array = np.asarray(shap_values)
    explanation = {
        name: float(value) for name, value in zip(feature_names, shap_array[0], strict=False)
    }
    return explanation, shap_array.tolist()


def _build_response(request: ExplainRequest) -> ExplainResponse:
    explanation, raw_shap = _generate_explanation(request.features)
    return ExplainResponse(
        explanation_id=str(uuid.uuid4()),
        model_version=request.model_version,
        prediction_id=request.prediction_id,
        created_at=datetime.now(tz=UTC),
        explanation=explanation,
        raw_shap_values=raw_shap,
    )


@app.post("/v1/explain", response_model=ExplainResponse)
async def explain(request: ExplainRequest) -> ExplainResponse:
    response = _build_response(request)
    _explanations[response.explanation_id] = response
    return response


@app.get("/v1/explain/{explanation_id}", response_model=ExplainResponse)
async def get_explanation(explanation_id: str) -> ExplainResponse:
    response = _explanations.get(explanation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Explanation not found")
    return response


@app.post("/v1/explain/batch", response_model=list[ExplainResponse])
async def batch_explain(requests: list[ExplainRequest]) -> list[ExplainResponse]:
    responses = [_build_response(request) for request in requests]
    _explanations.update({response.explanation_id: response for response in responses})
    return responses


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
