import hashlib
from pathlib import Path

import orjson
import yaml
from pydantic import BaseModel, Field


class FeatureSchemaManifest(BaseModel):
    feature_schema: str
    ordered_features: list[str] = Field(min_length=1)

    @property
    def schema_hash(self) -> str:
        payload = orjson.dumps(self.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(payload).hexdigest()


def load_feature_manifest(
    name: str = "surveillance-features-v2.yaml",
) -> FeatureSchemaManifest:
    path = Path(__file__).parents[1] / "feature_manifests" / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"feature manifest {path} must contain an object")
    return FeatureSchemaManifest.model_validate(data)
