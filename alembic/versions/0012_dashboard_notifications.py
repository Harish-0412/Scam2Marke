"""Add tenant notification channels, subscriptions, and delivery ledger.

Revision ID: 0012_notifications
Revises: 0011_live_checkpoints
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_notifications"
down_revision: str | None = "0011_live_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("notification_channels", "notification_subscriptions", "notification_deliveries")


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column(
            "channel_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("channel_type", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text()),
        sa.Column("config_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "notification_subscriptions",
        sa.Column(
            "subscription_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "channel_id",
            postgresql.UUID(),
            sa.ForeignKey("notification_channels.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("minimum_severity", sa.String(32), nullable=False, server_default="HIGH"),
        sa.Column("asset_ids_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("alert_types_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column(
            "delivery_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "channel_id",
            postgresql.UUID(),
            sa.ForeignKey("notification_channels.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("alert_id", postgresql.UUID()),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("response_code", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "event_id", name="uq_notification_channel_event"),
    )
    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        tenant_context = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"
        tenant_match = "tenant_id = current_setting('app.tenant_id', true)"
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
            USING ({tenant_context} OR {tenant_match})
            WITH CHECK ({tenant_context} OR {tenant_match})'''
        )
    op.create_index(
        "ix_notification_channels_channel_type", "notification_channels", ["channel_type"]
    )
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index(
        "ix_notification_deliveries_next_attempt_at", "notification_deliveries", ["next_attempt_at"]
    )
    op.create_index("ix_notification_deliveries_alert_id", "notification_deliveries", ["alert_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
