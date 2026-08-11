import json
import time
import urllib.request

BASE_URL = "http://localhost:8000"
REQUIRED_PATHS = {
    "/api/v1/watchlists",
    "/api/v1/assets/{asset_id}/overview",
    "/api/v1/assets/{asset_id}/timeline",
    "/api/v1/campaigns/{campaign_id}",
    "/api/v1/alerts/{alert_id}",
    "/api/v1/alerts/{alert_id}/acknowledge",
    "/api/v1/narratives/{narrative_id}",
    "/api/v1/replays/{replay_session_id}/start",
    "/api/v1/investigations/{investigation_id}",
}


def _json(path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=5) as response:
        return json.load(response)


def main() -> None:
    last_error: Exception | None = None
    for _ in range(60):
        try:
            health = _json("/api/v1/health")
            if health.get("status") == "ok":
                break
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    else:
        raise RuntimeError("API did not become healthy") from last_error
    schema = _json("/openapi.json")
    paths = set(schema.get("paths", {}))
    missing = sorted(REQUIRED_PATHS - paths)
    if missing:
        raise RuntimeError(f"release contract is missing paths: {missing}")
    config = _json("/api/v1/config")
    if config.get("api_contract") != "v1-frozen-2026-08-11":
        raise RuntimeError("API contract marker is not frozen")
    print(f"release verification passed with {len(paths)} API paths")


if __name__ == "__main__":
    main()
