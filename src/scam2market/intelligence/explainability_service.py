from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
import datetime
import joblib
import shap
import numpy as np
from typing import Dict, Any, List

app = FastAPI()

# Load a pretrained model (for demo we assume a scikit‑learn model saved at 'models/pretrained_model.joblib')
# In production this would be the actual risk scoring model.
try:
    _model = joblib.load('models/pretrained_model.joblib')
except Exception:
    _model = None  # Fallback stub model

# Initialize SHAP explainer (TreeExplainer for tree models, KernelExplainer otherwise)
if _model is not None:
    try:
        _explainer = shap.TreeExplainer(_model)
    except Exception:
        # KernelExplainer requires a background dataset; using zeros as placeholder
        _explainer = shap.KernelExplainer(_model.predict, np.zeros((1, len(_model.feature_names_in_))))
else:
    _explainer = None

class ExplainRequest(BaseModel):
    model_version: str
    prediction_id: str
    features: Dict[str, Any]

class ExplainResponse(BaseModel):
    explanation_id: str
    model_version: str
    prediction_id: str
    created_at: datetime.datetime
    explanation: Dict[str, float]
    raw_shap_values: Any = None

# In‑memory store for demo – replace with persistent DB table `ai_explanations`
_explanations: Dict[str, ExplainResponse] = {}

def _generate_explanation(features: Dict[str, Any]):
    if _model is None or _explainer is None:
        # Simple fallback: equal weight to each feature
        return {k: 1.0 / (i + 1) for i, k in enumerate(features.keys())}, None
    # Preserve feature order as provided
    feature_names = list(features.keys())
    X = np.array([features[name] for name in feature_names], dtype=float).reshape(1, -1)
    shap_vals = _explainer.shap_values(X)
    # Handle possible list output for classifiers
    if isinstance(shap_vals, list):
        shap_vals = shap_vals[0]
    explanation = {name: float(val) for name, val in zip(feature_names, shap_vals[0])}
    return explanation, shap_vals.tolist()

@app.post("/v1/explain", response_model=ExplainResponse)
async def explain(req: ExplainRequest):
    explanation, raw_shap = _generate_explanation(req.features)
    resp = ExplainResponse(
        explanation_id=str(uuid.uuid4()),
        model_version=req.model_version,
        prediction_id=req.prediction_id,
        created_at=datetime.datetime.utcnow(),
        explanation=explanation,
        raw_shap_values=raw_shap,
    )
    _explanations[resp.explanation_id] = resp
    return resp

@app.get("/v1/explain/{explanation_id}", response_model=ExplainResponse)
async def get_explanation(explanation_id: str):
    if explanation_id not in _explanations:
        raise HTTPException(status_code=404, detail="Explanation not found")
    return _explanations[explanation_id]

@app.post("/v1/explain/batch", response_model=List[ExplainResponse])
async def batch_explain(reqs: List[ExplainRequest]):
    responses: List[ExplainResponse] = []
    for req in reqs:
        explanation, raw_shap = _generate_explanation(req.features)
        resp = ExplainResponse(
            explanation_id=str(uuid.uuid4()),
            model_version=req.model_version,
            prediction_id=req.prediction_id,
            created_at=datetime.datetime.utcnow(),
            explanation=explanation,
            raw_shap_values=raw_shap,
        )
        _explanations[resp.explanation_id] = resp
        responses.append(resp)
    return responses

@app.get("/health")
async def health():
    return {"status": "ok"}
