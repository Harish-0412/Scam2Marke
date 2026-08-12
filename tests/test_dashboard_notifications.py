from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from scam2market.db.models import NotificationDeliveryModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.main import create_app
from scam2market.notifications.service import NotificationService
from scam2market.schemas.events import CanonicalEvent, EventType


def test_dashboard_static_workspace_is_served() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/dashboard/")
    assert response.status_code == 200
    assert "Scam2Market Analyst" in response.text
    assert "Alert queue" in response.text


def test_only_tenant_admin_can_create_notification_channels() -> None:
    with TestClient(create_app()) as client:
        denied = client.post(
            "/api/v1/notifications/channels",
            headers={"X-Dev-Roles": "ANALYST"},
            json={"name": "Denied", "channel_type": "WEBHOOK", "endpoint": "https://x.test"},
        )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_notification_delivery_is_tenant_scoped_idempotent_and_signed() -> None:
    suffix = uuid4().hex
    tenant_id = f"notifications-{suffix}"
    observed: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(202)

    headers = {"X-Tenant-ID": tenant_id, "X-Dev-Roles": "TENANT_ADMIN"}
    with TestClient(create_app()) as api_client:
        channel_response = api_client.post(
            "/api/v1/notifications/channels",
            headers=headers,
            json={
                "name": f"incident-webhook-{suffix}",
                "channel_type": "WEBHOOK",
                "endpoint": "https://notifications.test/incidents",
                "secret": "a-test-secret-with-enough-entropy",
            },
        )
        assert channel_response.status_code == 201, channel_response.text
        channel_id = channel_response.json()["channel_id"]
        subscription_response = api_client.post(
            "/api/v1/notifications/subscriptions",
            headers=headers,
            json={"channel_id": channel_id, "minimum_severity": "HIGH"},
        )
        assert subscription_response.status_code == 201, subscription_response.text

    now = datetime.now(tz=UTC)
    event = CanonicalEvent(
        event_type=EventType.alert_created,
        schema_version=1,
        source="campaign-engine",
        source_event_id=f"alert-{suffix}",
        asset_id="S2MUSDT",
        event_time=now,
        ingested_at=now,
        partition_key="S2MUSDT",
        payload={
            "tenant_id": tenant_id,
            "alert_id": str(uuid4()),
            "asset_id": "S2MUSDT",
            "alert_type": "CROSS_DOMAIN_MANIPULATION_RISK",
            "severity": "CRITICAL",
            "status": "ACTIVE",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
        service = NotificationService(AsyncSessionLocal, client=client)
        assert await service.enqueue(event, tenant_id) == 1
        assert await service.enqueue(event, tenant_id) == 0
        assert await service.deliver_due() == 1

    async with AsyncSessionLocal() as session:
        delivery = await session.scalar(
            select(NotificationDeliveryModel).where(
                NotificationDeliveryModel.tenant_id == tenant_id
            )
        )
    assert delivery is not None
    assert delivery.status == "DELIVERED"
    assert delivery.attempts == 1
    assert len(observed) == 1
    assert observed[0].headers["Idempotency-Key"] == event.event_id
    assert observed[0].headers["X-Scam2Market-Signature"].startswith("sha256=")
