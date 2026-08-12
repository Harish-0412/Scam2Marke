import asyncio
import hashlib
import hmac
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import httpx
import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    NotificationChannelModel,
    NotificationDeliveryModel,
    NotificationSubscriptionModel,
)
from scam2market.schemas.events import CanonicalEvent

SEVERITY_ORDER = {"INFO": 0, "NORMAL": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}


class NotificationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._sessions = sessions
        self._client = client

    async def enqueue(self, event: CanonicalEvent, tenant_id: str = "default") -> int:
        severity = str(event.payload.get("severity", "INFO")).upper()
        asset_id = str(event.payload.get("asset_id") or event.asset_id or "")
        alert_type = str(event.payload.get("alert_type", ""))
        async with self._sessions.begin() as session:
            subscriptions = (
                await session.execute(
                    select(NotificationSubscriptionModel, NotificationChannelModel)
                    .join(NotificationChannelModel)
                    .where(
                        NotificationSubscriptionModel.tenant_id == tenant_id,
                        NotificationSubscriptionModel.enabled.is_(True),
                        NotificationChannelModel.enabled.is_(True),
                    )
                )
            ).all()
            created = 0
            for subscription, channel in subscriptions:
                if not _matches(subscription, severity, asset_id, alert_type):
                    continue
                existing = await session.scalar(
                    select(NotificationDeliveryModel.delivery_id).where(
                        NotificationDeliveryModel.channel_id == channel.channel_id,
                        NotificationDeliveryModel.event_id == event.event_id,
                    )
                )
                if existing is not None:
                    continue
                session.add(
                    NotificationDeliveryModel(
                        tenant_id=tenant_id,
                        channel_id=channel.channel_id,
                        event_id=event.event_id,
                        alert_id=_uuid_or_none(event.payload.get("alert_id")),
                        payload_json=event.model_dump(mode="json"),
                    )
                )
                created += 1
            return created

    async def deliver_due(self, limit: int = 50) -> int:
        claimed = await self._claim_due(limit)
        for delivery_id, channel, envelope in claimed:
            try:
                response_code = await self._send(channel, envelope)
                await self._finalize(delivery_id, response_code=response_code)
            except Exception as exc:
                await self._finalize(delivery_id, error=str(exc))
        return len(claimed)

    async def _claim_due(
        self, limit: int
    ) -> list[tuple[UUID, NotificationChannelModel, dict[str, Any]]]:
        now = datetime.now(tz=UTC)
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    select(NotificationDeliveryModel, NotificationChannelModel)
                    .join(NotificationChannelModel)
                    .where(
                        NotificationDeliveryModel.status.in_(["PENDING", "RETRY"]),
                        NotificationDeliveryModel.next_attempt_at <= now,
                    )
                    .order_by(NotificationDeliveryModel.next_attempt_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
            claimed = []
            for delivery, channel in rows:
                delivery.attempts += 1
                delivery.status = "PROCESSING"
                claimed.append((delivery.delivery_id, channel, delivery.payload_json))
            return claimed

    async def _finalize(
        self,
        delivery_id: UUID,
        *,
        response_code: int | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        async with self._sessions.begin() as session:
            delivery = await session.get(
                NotificationDeliveryModel, delivery_id, with_for_update=True
            )
            if delivery is None or delivery.status != "PROCESSING":
                return
            if error is None:
                delivery.status = "DELIVERED"
                delivery.delivered_at = now
                delivery.response_code = response_code
                delivery.last_error = None
                return
            delivery.last_error = error[:2000]
            delivery.status = "FAILED" if delivery.attempts >= 5 else "RETRY"
            delivery.next_attempt_at = now + timedelta(seconds=min(900, 2**delivery.attempts * 5))

    async def _send(self, channel: NotificationChannelModel, envelope: dict[str, Any]) -> int:
        payload = _notification_payload(envelope)
        if channel.channel_type in {"SLACK", "TEAMS", "WEBHOOK"}:
            body = payload if channel.channel_type == "WEBHOOK" else _chat_payload(channel, payload)
            headers = {"Idempotency-Key": str(envelope.get("event_id", ""))}
            if channel.channel_type == "WEBHOOK" and channel.secret:
                serialized = orjson.dumps(body, option=orjson.OPT_SORT_KEYS)
                digest = hmac.new(channel.secret.encode(), serialized, hashlib.sha256).hexdigest()
                headers["X-Scam2Market-Signature"] = f"sha256={digest}"
            client = self._client or httpx.AsyncClient(timeout=10)
            try:
                response = await client.post(channel.endpoint, json=body, headers=headers)
                response.raise_for_status()
                return response.status_code
            finally:
                if self._client is None:
                    await client.aclose()
        if channel.channel_type == "EMAIL":
            await asyncio.to_thread(_send_email, channel, payload)
            return 250
        raise ValueError(f"unsupported notification channel: {channel.channel_type}")


def _matches(
    subscription: NotificationSubscriptionModel,
    severity: str,
    asset_id: str,
    alert_type: str,
) -> bool:
    if SEVERITY_ORDER.get(severity, 0) < SEVERITY_ORDER.get(subscription.minimum_severity, 2):
        return False
    if subscription.asset_ids_json and asset_id not in subscription.asset_ids_json:
        return False
    return not subscription.alert_types_json or alert_type in subscription.alert_types_json


def _notification_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = dict(envelope.get("payload", {}))
    return {
        "event_id": envelope.get("event_id"),
        "event_type": envelope.get("event_type"),
        "alert_id": payload.get("alert_id"),
        "campaign_id": payload.get("campaign_id"),
        "asset_id": payload.get("asset_id") or envelope.get("asset_id"),
        "alert_type": payload.get("alert_type"),
        "severity": payload.get("severity"),
        "status": payload.get("status"),
        "event_time": envelope.get("event_time"),
    }


def _chat_payload(channel: NotificationChannelModel, payload: dict[str, Any]) -> dict[str, Any]:
    text = (
        f"Scam2Market {payload.get('severity')} alert: {payload.get('alert_type')} "
        f"for {payload.get('asset_id')}"
    )
    return {"text": text} if channel.channel_type == "SLACK" else {"text": text, "type": "message"}


def _send_email(channel: NotificationChannelModel, payload: dict[str, Any]) -> None:
    config = channel.config_json
    message = EmailMessage()
    message["From"] = str(config.get("from", "scam2market@localhost"))
    message["To"] = channel.endpoint
    message["Subject"] = f"[{payload.get('severity')}] Scam2Market {payload.get('asset_id')}"
    message.set_content(str(payload))
    host = str(config.get("smtp_host", "localhost"))
    port = int(config.get("smtp_port", 25))
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if bool(config.get("starttls")):
            smtp.starttls()
        username = config.get("username")
        if username and channel.secret:
            smtp.login(str(username), channel.secret)
        smtp.send_message(message)


def _uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
