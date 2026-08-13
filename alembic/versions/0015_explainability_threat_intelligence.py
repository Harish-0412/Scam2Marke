"""Add durable score explanations and threat intelligence.

Revision ID: 0015_explain_threat
Revises: 0014_official_verification
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_explain_threat"
down_revision: str | None = "0014_official_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_scores", sa.Column("scope_id", sa.String(128)))
    op.execute(
        "UPDATE model_scores ms SET scope_id = fw.scope_id "
        "FROM feature_windows fw "
        "WHERE fw.feature_window_id = ms.feature_window_id"
    )
    op.alter_column("model_scores", "scope_id", nullable=False)
    op.create_index("ix_model_scores_scope_id", "model_scores", ["scope_id"])
    op.add_column("model_scores", sa.Column("threat_snapshot_id", postgresql.UUID()))
    op.add_column(
        "model_scores",
        sa.Column("threat_context_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "model_scores",
        sa.Column("decision_trace_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_model_scores_threat_snapshot_id", "model_scores", ["threat_snapshot_id"])

    op.add_column("threat_indicators", sa.Column("normalized_value", sa.Text()))
    op.add_column("threat_indicators", sa.Column("value_hash", sa.String(64)))
    op.add_column(
        "threat_indicators",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("threat_indicators", sa.Column("valid_from", sa.DateTime(timezone=True)))
    op.add_column("threat_indicators", sa.Column("valid_until", sa.DateTime(timezone=True)))
    op.add_column("threat_indicators", sa.Column("fetched_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE threat_indicators SET normalized_value = indicator_id, "
        "value_hash = encode(digest(indicator_id, 'sha256'), 'hex'), "
        "valid_from = first_seen, fetched_at = last_seen"
    )
    for column in ("normalized_value", "value_hash", "valid_from", "fetched_at"):
        op.alter_column("threat_indicators", column, nullable=False)
    op.create_unique_constraint(
        "uq_threat_indicator_value_hash", "threat_indicators", ["value_hash"]
    )
    op.create_index("ix_threat_indicators_value_hash", "threat_indicators", ["value_hash"])
    op.create_index("ix_threat_indicators_indicator_type", "threat_indicators", ["indicator_type"])

    op.create_table(
        "threat_observations",
        sa.Column("observation_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "indicator_id",
            sa.String(128),
            sa.ForeignKey("threat_indicators.indicator_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_indicator_id", sa.String(255), nullable=False),
        sa.Column("pulse_id", sa.String(255), nullable=False),
        sa.Column("tlp", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags_json", postgresql.JSONB(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "provider_indicator_id", name="uq_threat_provider_indicator"
        ),
    )
    op.create_table(
        "threat_feed_status",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("checkpoint_json", postgresql.JSONB(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("rate_limited_until", sa.DateTime(timezone=True)),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "threat_matches",
        sa.Column("match_id", postgresql.UUID(), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column(
            "post_id",
            sa.String(64),
            sa.ForeignKey("social_posts.post_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "indicator_id",
            sa.String(128),
            sa.ForeignKey("threat_indicators.indicator_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            postgresql.UUID(),
            sa.ForeignKey("threat_observations.observation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_type", sa.String(32), nullable=False),
        sa.Column("matched_value", sa.Text(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "threat_context_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("match_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope_id", "asset_id", "cutoff", "version", name="uq_threat_context_identity"
        ),
    )
    op.create_table(
        "model_explanations",
        sa.Column("explanation_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "model_score_id",
            postgresql.UUID(),
            sa.ForeignKey("model_scores.model_score_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("explanation_json", postgresql.JSONB(), nullable=False),
        sa.Column("explanation_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in {
        "threat_observations": ("indicator_id", "observed_at"),
        "threat_matches": ("scope_id", "asset_id", "post_id", "indicator_id", "event_time"),
        "threat_context_snapshots": ("scope_id", "asset_id", "cutoff"),
        "model_explanations": ("scope_id",),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "model_explanations",
        "threat_context_snapshots",
        "threat_matches",
        "threat_feed_status",
        "threat_observations",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_threat_indicator_value_hash", "threat_indicators", type_="unique")
    for column in (
        "fetched_at",
        "valid_until",
        "valid_from",
        "active",
        "value_hash",
        "normalized_value",
    ):
        op.drop_column("threat_indicators", column)
    for column in ("decision_trace_json", "threat_context_json", "threat_snapshot_id", "scope_id"):
        op.drop_column("model_scores", column)
