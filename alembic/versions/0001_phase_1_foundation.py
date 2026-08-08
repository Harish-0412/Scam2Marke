"""phase 1 foundation tables

Revision ID: 0001_phase_1
Revises:
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase_1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("quote_asset", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index("ix_assets_symbol", "assets", ["symbol"])

    op.create_table(
        "data_sources",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_id"),
    )

    op.create_table(
        "replay_sessions",
        sa.Column(
            "replay_session_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("speed_multiplier", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("replay_session_id"),
    )

    op.create_table(
        "event_ingestion_log",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("partition_key", sa.String(length=128), nullable=False),
        sa.Column("is_replay", sa.Boolean(), nullable=False),
        sa.Column("replay_session_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("dedupe_key", name="uq_event_ingestion_dedupe_key"),
    )
    op.create_index("ix_event_ingestion_log_dedupe_key", "event_ingestion_log", ["dedupe_key"])
    op.create_index("ix_event_ingestion_log_event_type", "event_ingestion_log", ["event_type"])
    op.create_index("ix_event_ingestion_log_asset_id", "event_ingestion_log", ["asset_id"])
    op.create_index("ix_event_ingestion_log_event_time", "event_ingestion_log", ["event_time"])
    op.create_index(
        "ix_event_ingestion_log_replay_session_id",
        "event_ingestion_log",
        ["replay_session_id"],
    )

    op.create_table(
        "schema_versions",
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("json_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compatibility", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("schema_name", "version"),
    )

    op.create_table(
        "system_config",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "audit_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=128), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("audit_id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("system_config")
    op.drop_table("schema_versions")
    op.drop_index("ix_event_ingestion_log_replay_session_id", table_name="event_ingestion_log")
    op.drop_index("ix_event_ingestion_log_event_time", table_name="event_ingestion_log")
    op.drop_index("ix_event_ingestion_log_asset_id", table_name="event_ingestion_log")
    op.drop_index("ix_event_ingestion_log_event_type", table_name="event_ingestion_log")
    op.drop_index("ix_event_ingestion_log_dedupe_key", table_name="event_ingestion_log")
    op.drop_table("event_ingestion_log")
    op.drop_table("replay_sessions")
    op.drop_table("data_sources")
    op.drop_index("ix_assets_symbol", table_name="assets")
    op.drop_table("assets")
