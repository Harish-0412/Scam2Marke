from fastapi.testclient import TestClient

from scam2market.main import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_config_includes_initial_topics() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/config")

    assert response.status_code == 200
    topics = response.json()["topics"]
    assert "market.trades.v1" in topics
    assert "alerts.events.v1" in topics
