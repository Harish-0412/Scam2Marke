"""campaign, narrative graph, and verification intelligence

Revision ID: 0004_campaign_graph_verification
Revises: 0003_review_corrections
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.type_api import TypeEngine

revision: str = "0004_campaign_graph_verification"
down_revision: str | None = "0003_review_corrections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> TypeEngine[object]:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.rename_table("event_outbox", "outbox_events")
    op.execute("ALTER INDEX ix_event_outbox_event_id RENAME TO ix_outbox_events_event_id")
    op.execute("ALTER INDEX ix_event_outbox_topic RENAME TO ix_outbox_events_topic")
    op.execute("ALTER INDEX ix_event_outbox_status RENAME TO ix_outbox_events_status")
    op.drop_constraint("uq_event_outbox_event_topic", "outbox_events", type_="unique")
    op.create_unique_constraint("uq_outbox_event_topic", "outbox_events", ["event_id", "topic"])

    op.add_column("model_scores", sa.Column("graph_score", sa.Float()))
    op.add_column(
        "model_scores",
        sa.Column(
            "stage_signals_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "campaigns",
        sa.Column("campaign_id", _uuid(), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("max_severity", sa.String(32), nullable=False),
        sa.Column("first_evidence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dominant_narrative_id", _uuid()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_campaigns_scope_id", "campaigns", ["scope_id"])
    op.create_index("ix_campaigns_asset_id", "campaigns", ["asset_id"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_index(
        "uq_campaign_active_scope_asset",
        "campaigns",
        ["scope_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index("ix_campaigns_dominant_narrative_id", "campaigns", ["dominant_narrative_id"])

    op.create_table(
        "campaign_evidence",
        sa.Column("evidence_event_id", sa.String(64), primary_key=True),
        sa.Column(
            "campaign_id",
            _uuid(),
            sa.ForeignKey("campaigns.campaign_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_campaign_evidence_campaign_id", "campaign_evidence", ["campaign_id"])

    op.create_table(
        "campaign_stage_history",
        sa.Column("stage_history_id", _uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            _uuid(),
            sa.ForeignKey("campaigns.campaign_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_stage", sa.String(64)),
        sa.Column("to_stage", sa.String(64), nullable=False),
        sa.Column("evidence_event_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "evidence_event_id", name="uq_campaign_stage_evidence"),
    )
    op.create_index(
        "ix_campaign_stage_history_campaign_id", "campaign_stage_history", ["campaign_id"]
    )

    op.create_table(
        "alerts",
        sa.Column("alert_id", _uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            _uuid(),
            sa.ForeignKey("campaigns.campaign_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "alert_type", name="uq_alert_campaign_type"),
    )
    op.create_index("ix_alerts_campaign_id", "alerts", ["campaign_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    op.create_table(
        "alert_state_history",
        sa.Column("alert_history_id", _uuid(), primary_key=True),
        sa.Column(
            "alert_id",
            _uuid(),
            sa.ForeignKey("alerts.alert_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_event_id", sa.String(64), nullable=False),
        sa.Column("from_severity", sa.String(32)),
        sa.Column("to_severity", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("suppression_reason", sa.String(128)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("alert_id", "evidence_event_id", name="uq_alert_state_evidence"),
    )
    op.create_index("ix_alert_state_history_alert_id", "alert_state_history", ["alert_id"])

    op.create_table(
        "narratives",
        sa.Column("narrative_id", _uuid(), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=False),
        sa.Column("unique_author_count", sa.Integer(), nullable=False),
        sa.Column("centroid_json", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "scope_id", "asset_id", "window_start", "cluster_key", name="uq_narrative_cluster"
        ),
    )
    op.create_index("ix_narratives_scope_id", "narratives", ["scope_id"])
    op.create_index("ix_narratives_asset_id", "narratives", ["asset_id"])
    op.create_index("ix_narratives_window_end", "narratives", ["window_end"])

    op.create_table(
        "narrative_posts",
        sa.Column(
            "narrative_id",
            _uuid(),
            sa.ForeignKey("narratives.narrative_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "post_id",
            sa.String(64),
            sa.ForeignKey("social_posts.post_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "graph_snapshots",
        sa.Column("graph_snapshot_id", _uuid(), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projection_version", sa.String(64), nullable=False),
        sa.Column("projection_status", sa.String(32), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("relationship_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_graph_snapshots_scope_id", "graph_snapshots", ["scope_id"])
    op.create_index("ix_graph_snapshots_asset_id", "graph_snapshots", ["asset_id"])

    op.create_table(
        "graph_features",
        sa.Column(
            "graph_snapshot_id",
            _uuid(),
            sa.ForeignKey("graph_snapshots.graph_snapshot_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_window_id",
            _uuid(),
            sa.ForeignKey("feature_windows.feature_window_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_revision", sa.Integer(), nullable=False),
        sa.Column("graph_score", sa.Float()),
        sa.Column("features_json", postgresql.JSONB(), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "disclosures",
        sa.Column("disclosure_id", _uuid(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_document_id", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(64)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_document_id", name="uq_disclosure_source_document"),
    )
    op.create_index("ix_disclosures_asset_id", "disclosures", ["asset_id"])
    op.create_index("ix_disclosures_published_at", "disclosures", ["published_at"])

    op.create_table(
        "disclosure_chunks",
        sa.Column("chunk_id", _uuid(), primary_key=True),
        sa.Column(
            "disclosure_id",
            _uuid(),
            sa.ForeignKey("disclosures.disclosure_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_disclosure_chunks_disclosure_id", "disclosure_chunks", ["disclosure_id"])

    op.create_table(
        "claims",
        sa.Column("claim_id", _uuid(), primary_key=True),
        sa.Column(
            "narrative_id",
            _uuid(),
            sa.ForeignKey("narratives.narrative_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extractor_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("narrative_id", "claim_hash", name="uq_narrative_claim_hash"),
    )
    op.create_index("ix_claims_narrative_id", "claims", ["narrative_id"])
    op.create_index("ix_claims_asset_id", "claims", ["asset_id"])

    op.create_table(
        "claim_verifications",
        sa.Column("verification_id", _uuid(), primary_key=True),
        sa.Column(
            "claim_id",
            _uuid(),
            sa.ForeignKey("claims.claim_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(64), nullable=False),
        sa.Column("claim_risk", sa.Float(), nullable=False),
        sa.Column("legitimate_event_score", sa.Float(), nullable=False),
        sa.Column("evidence_document_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("retrieval_metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("deterministic_reason", sa.Text(), nullable=False),
        sa.Column("llm_explanation", sa.Text()),
        sa.Column("verifier_version", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "claim_id", "alert_time", "verifier_version", name="uq_claim_verification_cutoff"
        ),
    )
    op.create_index("ix_claim_verifications_claim_id", "claim_verifications", ["claim_id"])
    op.create_index("ix_claim_verifications_result", "claim_verifications", ["result"])


def downgrade() -> None:
    op.drop_table("claim_verifications")
    op.drop_table("claims")
    op.drop_table("disclosure_chunks")
    op.drop_table("disclosures")
    op.drop_table("graph_features")
    op.drop_table("graph_snapshots")
    op.drop_table("narrative_posts")
    op.drop_table("narratives")
    op.drop_table("alert_state_history")
    op.drop_table("alerts")
    op.drop_table("campaign_stage_history")
    op.drop_table("campaign_evidence")
    op.drop_table("campaigns")
    op.drop_column("model_scores", "stage_signals_json")
    op.drop_column("model_scores", "graph_score")

    op.drop_constraint("uq_outbox_event_topic", "outbox_events", type_="unique")
    op.create_unique_constraint(
        "uq_event_outbox_event_topic", "outbox_events", ["event_id", "topic"]
    )
    op.execute("ALTER INDEX ix_outbox_events_status RENAME TO ix_event_outbox_status")
    op.execute("ALTER INDEX ix_outbox_events_topic RENAME TO ix_event_outbox_topic")
    op.execute("ALTER INDEX ix_outbox_events_event_id RENAME TO ix_event_outbox_event_id")
    op.rename_table("outbox_events", "event_outbox")
