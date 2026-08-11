from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any, cast

from fastapi.testclient import TestClient

from scam2market.api.routes.campaigns import get_realtime_broker
from scam2market.main import create_app
from scam2market.realtime import InMemoryRealtimeBroker


async def test_realtime_broker_replays_from_cursor() -> None:
    broker = InMemoryRealtimeBroker()
    stream_id = await broker.publish({"event_type": "alert.created", "severity": "HIGH"})

    subscription = cast(AsyncGenerator[tuple[str, dict[str, Any]], None], broker.subscribe("0-0"))
    async with aclosing(subscription):
        received_id, event = await anext(subscription)

    assert received_id == stream_id
    assert event["severity"] == "HIGH"


def test_websocket_receives_alert_event() -> None:
    import asyncio

    broker = InMemoryRealtimeBroker()
    asyncio.run(broker.publish({"event_type": "alert.created", "severity": "HIGH"}))
    app = create_app()
    app.dependency_overrides[get_realtime_broker] = lambda: broker

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/ws/alerts?after_id=0-0") as websocket,
    ):
        message = websocket.receive_json()

    assert message["stream_id"] == "1-0"
    assert message["event"]["event_type"] == "alert.created"
