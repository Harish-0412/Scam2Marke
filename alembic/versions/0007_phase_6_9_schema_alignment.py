"""Align Phase 6-9 persistence models with reviewed runtime contracts.

Revision ID: 0007_phase_6_9_schema_alignment
Revises: 0006_add_scope_id
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase_6_9_schema_alignment"
down_revision: str | None = "0006_add_scope_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _upgrade_fusion()
    _upgrade_campaigns()
    _upgrade_narratives()
    _upgrade_graph()
    _upgrade_verification()
    _create_phase_9_tables()


def _upgrade_fusion() -> None:
    op.drop_constraint("uq_model_score_window_revision_version", "model_scores", type_="unique")
    op.add_column("model_scores", sa.Column("base_model_version", sa.String(64)))
    op.add_column("model_scores", sa.Column("fusion_policy_version", sa.String(64)))
    op.add_column("model_scores", sa.Column("enrichment_profile", sa.String(32)))
    op.add_column("model_scores", sa.Column("fusion_revision", sa.Integer()))
    op.add_column("model_scores", sa.Column("evidence_cutoff", sa.DateTime(timezone=True)))
    op.add_column(
        "model_scores",
        sa.Column(
            "input_snapshot_ids_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("model_scores", sa.Column("idempotency_key", sa.String(64)))
    op.execute(
        "UPDATE model_scores SET enrichment_profile = CASE "
        "WHEN model_version LIKE '%graph%verification%' THEN 'GRAPH_AND_VERIFICATION' "
        "WHEN model_version LIKE '%graph%' THEN 'GRAPH' "
        "WHEN model_version LIKE '%verification%' THEN 'VERIFICATION' "
        "ELSE 'BASE' END"
    )
    op.execute(
        "UPDATE model_scores SET fusion_revision = CASE enrichment_profile "
        "WHEN 'BASE' THEN 1 WHEN 'GRAPH_AND_VERIFICATION' THEN 3 ELSE 2 END"
    )
    op.execute(
        "UPDATE model_scores SET base_model_version = split_part(model_version, '+', 1), "
        "fusion_policy_version = 'fusion-policy-v1', "
        "idempotency_key = md5(model_score_id::text)"
    )
    op.execute(
        "UPDATE model_scores AS score SET evidence_cutoff = feature_window.window_end "
        "FROM feature_windows AS feature_window "
        "WHERE score.feature_window_id = feature_window.feature_window_id"
    )
    op.execute("UPDATE model_scores SET evidence_cutoff = scored_at WHERE evidence_cutoff IS NULL")
    for column in (
        "base_model_version",
        "fusion_policy_version",
        "enrichment_profile",
        "fusion_revision",
        "evidence_cutoff",
        "idempotency_key",
    ):
        op.alter_column("model_scores", column, nullable=False)
    op.alter_column("model_scores", "input_snapshot_ids_json", server_default=None)
    op.create_index("ix_model_scores_enrichment_profile", "model_scores", ["enrichment_profile"])
    op.create_unique_constraint(
        "uq_model_score_idempotency_key", "model_scores", ["idempotency_key"]
    )


def _upgrade_campaigns() -> None:
    op.create_unique_constraint(
        "uq_campaign_evidence_scope_event",
        "campaign_evidence",
        ["scope_id", "evidence_event_id"],
    )
    op.add_column(
        "campaigns",
        sa.Column("stage_confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "stage_reason_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "stage_rule_version",
            sa.String(64),
            nullable=False,
            server_default="campaign-stage-rules-v2",
        ),
    )
    op.add_column(
        "campaigns", sa.Column("last_applied_evidence_cutoff", sa.DateTime(timezone=True))
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "last_applied_feature_revision", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column("last_applied_fusion_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "last_applied_enrichment_profile",
            sa.String(32),
            nullable=False,
            server_default="BASE",
        ),
    )
    op.add_column("campaigns", sa.Column("closed_reason", sa.String(64)))
    op.execute("UPDATE campaigns SET stage = 'POSSIBLE_DISTRIBUTION' WHERE stage = 'DISTRIBUTION'")
    op.execute(
        "UPDATE campaigns SET last_applied_evidence_cutoff = last_evidence_at "
        "WHERE last_applied_evidence_cutoff IS NULL"
    )
    op.alter_column(
        "campaign_stage_history", "transitioned_at", new_column_name="changed_at_event_time"
    )
    op.add_column(
        "campaign_stage_history",
        sa.Column(
            "reason_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "campaign_stage_history",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaign_stage_history",
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default="campaign-stage-rules-v2",
        ),
    )
    op.add_column(
        "campaign_stage_history",
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def _upgrade_narratives() -> None:
    op.drop_constraint("uq_narrative_cluster", "narratives", type_="unique")
    op.add_column("narratives", sa.Column("stable_key", sa.String(255)))
    op.add_column("narratives", sa.Column("current_revision_id", postgresql.UUID()))
    op.add_column("narratives", sa.Column("current_revision", sa.Integer()))
    op.add_column("narratives", sa.Column("member_hash", sa.String(64)))
    op.add_column("narratives", sa.Column("first_seen", sa.DateTime(timezone=True)))
    op.add_column("narratives", sa.Column("last_seen", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE narratives SET stable_key = window_start::text || ':' || narrative_id::text, "
        "current_revision_id = narrative_id, current_revision = 1, member_hash = cluster_key, "
        "first_seen = window_start, last_seen = window_end"
    )
    for column in (
        "stable_key",
        "current_revision_id",
        "current_revision",
        "member_hash",
        "first_seen",
        "last_seen",
    ):
        op.alter_column("narratives", column, nullable=False)
    op.create_unique_constraint(
        "uq_narrative_stable_key", "narratives", ["scope_id", "asset_id", "stable_key"]
    )
    op.create_table(
        "narrative_revisions",
        sa.Column("narrative_revision_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "narrative_id",
            postgresql.UUID(),
            sa.ForeignKey("narratives.narrative_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("member_hash", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("centroid_json", postgresql.JSONB(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("narrative_id", "revision", name="uq_narrative_revision_number"),
        sa.UniqueConstraint("narrative_id", "member_hash", name="uq_narrative_revision_members"),
    )
    op.create_index("ix_narrative_revisions_narrative_id", "narrative_revisions", ["narrative_id"])
    op.execute(
        "INSERT INTO narrative_revisions (narrative_revision_id, narrative_id, revision, "
        "member_hash, window_start, cutoff_event_time, label, summary, centroid_json, post_count) "
        "SELECT narrative_id, narrative_id, 1, cluster_key, window_start, window_end, label, "
        "summary, centroid_json, post_count FROM narratives"
    )
    op.add_column("narrative_posts", sa.Column("narrative_revision_id", postgresql.UUID()))
    op.execute("UPDATE narrative_posts SET narrative_revision_id = narrative_id")
    op.alter_column("narrative_posts", "narrative_revision_id", nullable=False)
    op.drop_constraint("narrative_posts_pkey", "narrative_posts", type_="primary")
    op.create_foreign_key(
        "fk_narrative_posts_revision",
        "narrative_posts",
        "narrative_revisions",
        ["narrative_revision_id"],
        ["narrative_revision_id"],
        ondelete="CASCADE",
    )
    op.create_primary_key(
        "narrative_posts_pkey", "narrative_posts", ["narrative_revision_id", "post_id"]
    )
    op.create_index("ix_narrative_posts_narrative_id", "narrative_posts", ["narrative_id"])


def _upgrade_graph() -> None:
    op.add_column("graph_snapshots", sa.Column("cutoff_event_time", sa.DateTime(timezone=True)))
    op.add_column("graph_snapshots", sa.Column("source_lineage_hash", sa.String(64)))
    op.add_column(
        "graph_snapshots",
        sa.Column(
            "component_status_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        "UPDATE graph_snapshots SET cutoff_event_time = window_end, "
        "source_lineage_hash = md5(graph_snapshot_id::text)"
    )
    op.alter_column("graph_snapshots", "cutoff_event_time", nullable=False)
    op.alter_column("graph_snapshots", "source_lineage_hash", nullable=False)
    op.alter_column("graph_snapshots", "component_status_json", server_default=None)


def _upgrade_verification() -> None:
    op.drop_constraint("uq_disclosure_source_document", "disclosures", type_="unique")
    op.add_column("disclosures", sa.Column("ingested_at", sa.DateTime(timezone=True)))
    op.add_column(
        "disclosures",
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("disclosures", sa.Column("supersedes_disclosure_id", postgresql.UUID()))
    op.add_column(
        "disclosures",
        sa.Column(
            "source_policy_version",
            sa.String(64),
            nullable=False,
            server_default="official-sources-v1",
        ),
    )
    op.execute("UPDATE disclosures SET ingested_at = retrieved_at WHERE ingested_at IS NULL")
    op.alter_column("disclosures", "ingested_at", nullable=False)
    op.create_foreign_key(
        "fk_disclosures_supersedes",
        "disclosures",
        "disclosures",
        ["supersedes_disclosure_id"],
        ["disclosure_id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_disclosure_version",
        "disclosures",
        ["source", "source_document_id", "document_version"],
    )
    op.add_column("claims", sa.Column("claim_type", sa.String(64)))
    op.add_column("claims", sa.Column("canonical_json", postgresql.JSONB()))
    op.execute(
        "UPDATE claims SET claim_type = 'OTHER', "
        "canonical_json = jsonb_build_object('legacy_claim_hash', claim_hash)"
    )
    op.alter_column("claims", "claim_type", nullable=False)
    op.alter_column("claims", "canonical_json", nullable=False)
    op.add_column(
        "claim_verifications",
        sa.Column(
            "source_policy_version",
            sa.String(64),
            nullable=False,
            server_default="official-sources-v1",
        ),
    )


def _create_phase_9_tables() -> None:
    op.create_table(
        "threat_indicators",
        sa.Column("indicator_id", sa.String(128), primary_key=True),
        sa.Column("indicator_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "raw_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "explainability_outputs",
        sa.Column(
            "output_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "claim_id",
            postgresql.UUID(),
            sa.ForeignKey("claims.claim_id"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_explainability_outputs_claim_id", "explainability_outputs", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_explainability_outputs_claim_id", table_name="explainability_outputs")
    op.drop_table("explainability_outputs")
    op.drop_table("threat_indicators")
    op.drop_column("claim_verifications", "source_policy_version")
    op.drop_column("claims", "canonical_json")
    op.drop_column("claims", "claim_type")
    op.drop_constraint("uq_disclosure_version", "disclosures", type_="unique")
    op.drop_constraint("fk_disclosures_supersedes", "disclosures", type_="foreignkey")
    op.drop_column("disclosures", "source_policy_version")
    op.drop_column("disclosures", "supersedes_disclosure_id")
    op.drop_column("disclosures", "document_version")
    op.drop_column("disclosures", "ingested_at")
    op.create_unique_constraint(
        "uq_disclosure_source_document", "disclosures", ["source", "source_document_id"]
    )
    op.drop_column("graph_snapshots", "component_status_json")
    op.drop_column("graph_snapshots", "source_lineage_hash")
    op.drop_column("graph_snapshots", "cutoff_event_time")
    op.drop_index("ix_narrative_posts_narrative_id", table_name="narrative_posts")
    op.drop_constraint("narrative_posts_pkey", "narrative_posts", type_="primary")
    op.drop_constraint("fk_narrative_posts_revision", "narrative_posts", type_="foreignkey")
    op.create_primary_key("narrative_posts_pkey", "narrative_posts", ["narrative_id", "post_id"])
    op.drop_column("narrative_posts", "narrative_revision_id")
    op.drop_index("ix_narrative_revisions_narrative_id", table_name="narrative_revisions")
    op.drop_table("narrative_revisions")
    op.drop_constraint("uq_narrative_stable_key", "narratives", type_="unique")
    for column in (
        "last_seen",
        "first_seen",
        "member_hash",
        "current_revision",
        "current_revision_id",
        "stable_key",
    ):
        op.drop_column("narratives", column)
    op.create_unique_constraint(
        "uq_narrative_cluster",
        "narratives",
        ["scope_id", "asset_id", "window_start", "cluster_key"],
    )
    op.drop_column("campaign_stage_history", "recorded_at")
    op.drop_column("campaign_stage_history", "rule_version")
    op.drop_column("campaign_stage_history", "confidence")
    op.drop_column("campaign_stage_history", "reason_json")
    op.alter_column(
        "campaign_stage_history", "changed_at_event_time", new_column_name="transitioned_at"
    )
    for column in (
        "closed_reason",
        "last_applied_enrichment_profile",
        "last_applied_fusion_revision",
        "last_applied_feature_revision",
        "last_applied_evidence_cutoff",
        "stage_rule_version",
        "stage_reason_json",
        "stage_confidence",
    ):
        op.drop_column("campaigns", column)
    op.drop_constraint("uq_campaign_evidence_scope_event", "campaign_evidence", type_="unique")
    # The legacy schema can store only one score per window/model tuple. Keep the
    # most enriched, most recent revision when collapsing back to that contract.
    op.execute(
        "WITH ranked_scores AS ("
        "SELECT model_score_id, row_number() OVER ("
        "PARTITION BY feature_window_id, feature_revision, model_version "
        "ORDER BY fusion_revision DESC, scored_at DESC, model_score_id DESC"
        ") AS rank FROM model_scores) "
        "DELETE FROM model_scores AS score USING ranked_scores AS ranked "
        "WHERE score.model_score_id = ranked.model_score_id AND ranked.rank > 1"
    )
    op.drop_constraint("uq_model_score_idempotency_key", "model_scores", type_="unique")
    op.drop_index("ix_model_scores_enrichment_profile", table_name="model_scores")
    for column in (
        "idempotency_key",
        "input_snapshot_ids_json",
        "evidence_cutoff",
        "fusion_revision",
        "enrichment_profile",
        "fusion_policy_version",
        "base_model_version",
    ):
        op.drop_column("model_scores", column)
    op.create_unique_constraint(
        "uq_model_score_window_revision_version",
        "model_scores",
        ["feature_window_id", "feature_revision", "model_version"],
    )
