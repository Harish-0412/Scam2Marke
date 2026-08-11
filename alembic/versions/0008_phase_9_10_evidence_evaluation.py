"""Add immutable evidence, investigations, replay evaluation, and model lineage.

Revision ID: 0008_phase_9_10
Revises: 0007_phase_6_9_schema_alignment
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_phase_9_10"
down_revision: str | None = "0007_phase_6_9_schema_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _upgrade_replay_sessions()
    _create_evidence_tables()
    _create_investigation_tables()
    _create_evaluation_tables()
    _protect_evidence_ledger()


def _upgrade_replay_sessions() -> None:
    op.add_column("replay_sessions", sa.Column("scope_id", sa.String(128)))
    op.add_column("replay_sessions", sa.Column("scenario_version", sa.Integer()))
    op.add_column("replay_sessions", sa.Column("manifest_hash", sa.String(64)))
    op.add_column("replay_sessions", sa.Column("random_seed", sa.Integer()))
    op.add_column("replay_sessions", sa.Column("virtual_clock_at", sa.DateTime(timezone=True)))
    op.add_column("replay_sessions", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column("replay_sessions", sa.Column("requested_by", sa.String(128)))
    op.add_column(
        "replay_sessions",
        sa.Column(
            "configuration_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("replay_sessions", sa.Column("failure_reason", sa.Text()))
    op.execute(
        "UPDATE replay_sessions SET "
        "scope_id = replay_session_id::text, scenario_version = 1, "
        "manifest_hash = encode(digest(dataset_id, 'sha256'), 'hex'), random_seed = 0"
    )
    for column in ("scope_id", "scenario_version", "manifest_hash", "random_seed"):
        op.alter_column("replay_sessions", column, nullable=False)
    op.create_unique_constraint("uq_replay_session_scope", "replay_sessions", ["scope_id"])


def _create_evidence_tables() -> None:
    op.create_table(
        "evidence_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "alert_id",
            postgresql.UUID(),
            sa.ForeignKey("alerts.alert_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(),
            sa.ForeignKey("campaigns.campaign_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("alert_version", sa.Integer(), nullable=False),
        sa.Column("evidence_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("previous_chain_hash", sa.String(64)),
        sa.Column("chain_hash", sa.String(64), nullable=False),
        sa.Column("completeness_score", sa.Float(), nullable=False),
        sa.Column("completeness_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("alert_id", "alert_version", name="uq_evidence_alert_version"),
        sa.UniqueConstraint("content_hash", name="uq_evidence_content_hash"),
        sa.UniqueConstraint("chain_hash", name="uq_evidence_chain_hash"),
    )
    for column in ("alert_id", "campaign_id", "scope_id", "asset_id"):
        op.create_index(f"ix_evidence_snapshots_{column}", "evidence_snapshots", [column])
    op.create_table(
        "alert_evidence",
        sa.Column(
            "alert_evidence_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(),
            sa.ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "alert_id",
            postgresql.UUID(),
            sa.ForeignKey("alerts.alert_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id", "evidence_type", "evidence_id", name="uq_snapshot_evidence_ref"
        ),
    )
    op.create_index("ix_alert_evidence_snapshot_id", "alert_evidence", ["snapshot_id"])
    op.create_index("ix_alert_evidence_alert_id", "alert_evidence", ["alert_id"])
    op.create_table(
        "explanations",
        sa.Column("explanation_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(),
            sa.ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("triggered_rules_json", postgresql.JSONB(), nullable=False),
        sa.Column("contributors_json", postgresql.JSONB(), nullable=False),
        sa.Column("context_json", postgresql.JSONB(), nullable=False),
        sa.Column("llm_summary", sa.Text()),
        sa.Column("llm_status", sa.String(32), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_explanations_snapshot_id", "explanations", ["snapshot_id"])


def _create_investigation_tables() -> None:
    op.create_table(
        "investigations",
        sa.Column(
            "investigation_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "alert_id",
            postgresql.UUID(),
            sa.ForeignKey("alerts.alert_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(),
            sa.ForeignKey("evidence_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False),
        sa.Column("assigned_to", sa.String(128)),
        sa.Column("tags_json", postgresql.JSONB(), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("disposition", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("opened_by", sa.String(128), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("scope_id", "alert_id", "status", "assigned_to", "sla_due_at"):
        op.create_index(f"ix_investigations_{column}", "investigations", [column])
    op.create_table(
        "investigation_events",
        sa.Column(
            "investigation_event_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "investigation_id",
            postgresql.UUID(),
            sa.ForeignKey("investigations.investigation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_investigation_events_investigation_id", "investigation_events", ["investigation_id"]
    )
    op.create_table(
        "analyst_feedback",
        sa.Column(
            "feedback_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "investigation_id",
            postgresql.UUID(),
            sa.ForeignKey("investigations.investigation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_id", postgresql.UUID(), sa.ForeignKey("alerts.alert_id"), nullable=False),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(),
            sa.ForeignKey("evidence_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("analyst_id", sa.String(128), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("adjudicated_by", sa.String(128)),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True)),
        sa.Column("adjudication_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("investigation_id", "alert_id", "label"):
        op.create_index(f"ix_analyst_feedback_{column}", "analyst_feedback", [column])


def _create_evaluation_tables() -> None:
    op.create_table(
        "replay_evaluations",
        sa.Column("evaluation_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "replay_session_id",
            postgresql.UUID(),
            sa.ForeignKey("replay_sessions.replay_session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluation_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("mlflow_run_id", sa.String(128)),
        sa.UniqueConstraint(
            "replay_session_id", "evaluation_version", name="uq_replay_evaluation_version"
        ),
    )
    op.create_index(
        "ix_replay_evaluations_replay_session_id",
        "replay_evaluations",
        ["replay_session_id"],
    )
    op.create_table(
        "ablation_results",
        sa.Column("ablation_result_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(),
            sa.ForeignKey("replay_evaluations.evaluation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("component_set_json", postgresql.JSONB(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("contribution_delta", sa.Float(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("evaluation_id", "profile", name="uq_evaluation_ablation_profile"),
    )
    op.create_index("ix_ablation_results_evaluation_id", "ablation_results", ["evaluation_id"])
    op.create_table(
        "model_artifacts",
        sa.Column("model_artifact_id", postgresql.UUID(), primary_key=True),
        sa.Column("model_family", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("input_schema_hash", sa.String(64), nullable=False),
        sa.Column("training_data_hash", sa.String(64)),
        sa.Column("mlflow_run_id", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("model_family", "model_version", name="uq_model_family_version"),
    )
    op.create_index("ix_model_artifacts_model_family", "model_artifacts", ["model_family"])
    op.create_table(
        "model_aliases",
        sa.Column("model_family", sa.String(128), primary_key=True),
        sa.Column("alias", sa.String(32), primary_key=True),
        sa.Column(
            "model_artifact_id",
            postgresql.UUID(),
            sa.ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("assigned_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "shadow_scores",
        sa.Column("shadow_score_id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "replay_session_id",
            postgresql.UUID(),
            sa.ForeignKey("replay_sessions.replay_session_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "feature_window_id",
            postgresql.UUID(),
            sa.ForeignKey("feature_windows.feature_window_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_revision", sa.Integer(), nullable=False),
        sa.Column(
            "model_artifact_id",
            postgresql.UUID(),
            sa.ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "champion_model_score_id",
            postgresql.UUID(),
            sa.ForeignKey("model_scores.model_score_id", ondelete="SET NULL"),
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("controls_alerts", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("agreement", sa.Boolean()),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "feature_window_id", "feature_revision", "model_artifact_id", name="uq_shadow_score"
        ),
        sa.CheckConstraint("controls_alerts = false", name="ck_shadow_scores_never_control_alerts"),
    )
    op.create_index("ix_shadow_scores_replay_session_id", "shadow_scores", ["replay_session_id"])


def _protect_evidence_ledger() -> None:
    op.execute(
        "CREATE FUNCTION reject_evidence_mutation() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'evidence ledger records are immutable'; END; "
        "$$ LANGUAGE plpgsql"
    )
    for table in ("evidence_snapshots", "alert_evidence", "explanations"):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()"
        )


def downgrade() -> None:
    for table in ("explanations", "alert_evidence", "evidence_snapshots"):
        op.execute(f"DROP TRIGGER IF EXISTS protect_{table} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_evidence_mutation()")
    for table in (
        "shadow_scores",
        "model_aliases",
        "model_artifacts",
        "ablation_results",
        "replay_evaluations",
        "analyst_feedback",
        "investigation_events",
        "investigations",
        "explanations",
        "alert_evidence",
        "evidence_snapshots",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_replay_session_scope", "replay_sessions", type_="unique")
    for column in (
        "failure_reason",
        "configuration_json",
        "requested_by",
        "paused_at",
        "virtual_clock_at",
        "random_seed",
        "manifest_hash",
        "scenario_version",
        "scope_id",
    ):
        op.drop_column("replay_sessions", column)
