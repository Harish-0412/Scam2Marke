"""phase 2-5 architecture review corrections

Revision ID: 0003_review_corrections
Revises: 0002_ingestion_features
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_review_corrections"
down_revision: str | None = "0002_ingestion_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_SCHEMA_HASH = "0" * 64


def upgrade() -> None:
    op.add_column(
        "event_ingestion_log", sa.Column("origin_event_id", sa.String(512), nullable=True)
    )
    op.add_column(
        "event_ingestion_log", sa.Column("delivery_event_id", sa.String(64), nullable=True)
    )
    op.execute(
        "UPDATE event_ingestion_log "
        "SET origin_event_id = source || ':' || source_event_id, delivery_event_id = event_id"
    )
    op.alter_column("event_ingestion_log", "origin_event_id", nullable=False)
    op.alter_column("event_ingestion_log", "delivery_event_id", nullable=False)
    op.create_index(
        "ix_event_ingestion_log_origin_event_id",
        "event_ingestion_log",
        ["origin_event_id"],
    )
    op.create_unique_constraint(
        "uq_event_ingestion_delivery_event_id",
        "event_ingestion_log",
        ["delivery_event_id"],
    )

    op.drop_constraint("event_outbox_event_id_fkey", "event_outbox", type_="foreignkey")
    op.add_column("event_outbox", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("event_outbox", sa.Column("last_error", sa.Text()))

    op.create_table(
        "worker_checkpoints",
        sa.Column("consumer_group", sa.String(128), primary_key=True),
        sa.Column("topic", sa.String(128), primary_key=True),
        sa.Column("partition", sa.Integer(), primary_key=True),
        sa.Column("last_durable_offset", sa.BigInteger(), nullable=False),
        sa.Column("feature_state_version", sa.String(128)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.add_column(
        "orderbook_snapshots",
        sa.Column("orderbook_state", sa.String(32), nullable=False, server_default="VALID"),
    )
    op.add_column(
        "orderbook_snapshots",
        sa.Column("book_valid", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "orderbook_features",
        sa.Column("book_valid", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.add_column(
        "social_posts",
        sa.Column("pseudonym_key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "post_asset_mentions",
        sa.Column(
            "resolution_reason",
            sa.String(128),
            nullable=False,
            server_default="LEGACY_UNSPECIFIED",
        ),
    )

    op.add_column(
        "feature_windows",
        sa.Column(
            "revision_state",
            sa.String(32),
            nullable=False,
            server_default="PROVISIONAL",
        ),
    )
    op.execute(
        "UPDATE feature_windows SET revision_state = "
        "CASE WHEN is_final THEN 'FINAL' ELSE 'PROVISIONAL' END"
    )
    op.add_column(
        "feature_windows",
        sa.Column(
            "feature_schema_hash",
            sa.String(64),
            nullable=False,
            server_default=_LEGACY_SCHEMA_HASH,
        ),
    )
    op.add_column(
        "feature_revisions",
        sa.Column(
            "revision_state",
            sa.String(32),
            nullable=False,
            server_default="PROVISIONAL",
        ),
    )
    op.execute(
        "UPDATE feature_revisions SET revision_state = "
        "CASE WHEN is_final THEN 'FINAL' ELSE 'PROVISIONAL' END"
    )
    op.add_column("feature_revisions", sa.Column("supersedes_revision", sa.Integer()))
    op.add_column(
        "feature_revisions",
        sa.Column(
            "feature_schema_hash",
            sa.String(64),
            nullable=False,
            server_default=_LEGACY_SCHEMA_HASH,
        ),
    )

    op.add_column("model_scores", sa.Column("market_anomaly_risk", sa.Float()))
    op.add_column(
        "model_scores",
        sa.Column(
            "market_anomaly_severity",
            sa.String(32),
            nullable=False,
            server_default="NORMAL",
        ),
    )
    op.add_column("model_scores", sa.Column("social_coordination_risk", sa.Float()))
    op.add_column(
        "model_scores",
        sa.Column(
            "social_coordination_severity",
            sa.String(32),
            nullable=False,
            server_default="NORMAL",
        ),
    )
    op.add_column(
        "model_scores",
        sa.Column("raw_cross_domain_risk", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_scores",
        sa.Column("context_adjusted_risk", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_scores",
        sa.Column("market_regime_confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_scores",
        sa.Column("liquidity_confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE model_scores SET "
        "market_anomaly_risk = market_score, "
        "market_anomaly_severity = severity, "
        "social_coordination_risk = coordination_score, "
        "social_coordination_severity = severity, "
        "raw_cross_domain_risk = fusion_score, "
        "context_adjusted_risk = fusion_score, "
        "market_regime_confidence = confidence, "
        "liquidity_confidence = confidence"
    )


def downgrade() -> None:
    op.drop_column("model_scores", "liquidity_confidence")
    op.drop_column("model_scores", "market_regime_confidence")
    op.drop_column("model_scores", "context_adjusted_risk")
    op.drop_column("model_scores", "raw_cross_domain_risk")
    op.drop_column("model_scores", "social_coordination_severity")
    op.drop_column("model_scores", "social_coordination_risk")
    op.drop_column("model_scores", "market_anomaly_severity")
    op.drop_column("model_scores", "market_anomaly_risk")

    op.drop_column("feature_revisions", "feature_schema_hash")
    op.drop_column("feature_revisions", "supersedes_revision")
    op.drop_column("feature_revisions", "revision_state")
    op.drop_column("feature_windows", "feature_schema_hash")
    op.drop_column("feature_windows", "revision_state")

    op.drop_column("post_asset_mentions", "resolution_reason")
    op.drop_column("social_posts", "pseudonym_key_version")
    op.drop_column("orderbook_features", "book_valid")
    op.drop_column("orderbook_snapshots", "book_valid")
    op.drop_column("orderbook_snapshots", "orderbook_state")

    op.drop_table("worker_checkpoints")
    op.drop_column("event_outbox", "last_error")
    op.drop_column("event_outbox", "claimed_at")
    op.execute(
        "DELETE FROM event_outbox outbox WHERE NOT EXISTS "
        "(SELECT 1 FROM event_ingestion_log log WHERE log.event_id = outbox.event_id)"
    )
    op.create_foreign_key(
        "event_outbox_event_id_fkey",
        "event_outbox",
        "event_ingestion_log",
        ["event_id"],
        ["event_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "uq_event_ingestion_delivery_event_id",
        "event_ingestion_log",
        type_="unique",
    )
    op.drop_index("ix_event_ingestion_log_origin_event_id", table_name="event_ingestion_log")
    op.drop_column("event_ingestion_log", "delivery_event_id")
    op.drop_column("event_ingestion_log", "origin_event_id")
