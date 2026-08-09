from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScenarioExpectations(BaseModel):
    watch_before: datetime
    high_before: datetime
    critical_requires_market_corroboration: bool = True


class ScenarioEventCounts(BaseModel):
    market: int = Field(ge=0)
    social: int = Field(ge=0)


class ScenarioManifest(BaseModel):
    scenario_id: str
    scenario_version: int = Field(ge=1)
    seed: int
    asset_id: str
    timeline: dict[str, datetime]
    expectations: ScenarioExpectations
    expected_event_counts: ScenarioEventCounts


def load_scenario_manifest(name: str = "synthetic-pump-v1.yaml") -> ScenarioManifest:
    path = Path(__file__).parents[1] / "scenario_manifests" / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"scenario manifest {path} must contain an object")
    return ScenarioManifest.model_validate(data)
