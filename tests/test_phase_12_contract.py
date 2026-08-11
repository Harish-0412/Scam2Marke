from fastapi.testclient import TestClient

from scam2market.main import create_app


def test_frozen_analyst_contract_is_exposed() -> None:
    client = TestClient(create_app())
    schema = client.get("/openapi.json").json()
    required = {
        "/api/v1/watchlists",
        "/api/v1/assets/{asset_id}/overview",
        "/api/v1/assets/{asset_id}/scores",
        "/api/v1/assets/{asset_id}/timeline",
        "/api/v1/campaigns/{campaign_id}",
        "/api/v1/alerts/{alert_id}",
        "/api/v1/alerts/{alert_id}/acknowledge",
        "/api/v1/assets/{asset_id}/narratives",
        "/api/v1/narratives/{narrative_id}",
        "/api/v1/replays/{replay_session_id}/start",
        "/api/v1/replays/{replay_session_id}/pause",
        "/api/v1/operations/model-drift",
        "/api/v1/operations/policy-proposals",
    }
    assert required <= set(schema["paths"])

    config = client.get("/api/v1/config")
    assert config.status_code == 200
    assert config.json()["api_contract"] == "v1-frozen-2026-08-11"


def test_metrics_are_integrated_into_main_api() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "scam2market_http_requests_total" in response.text
