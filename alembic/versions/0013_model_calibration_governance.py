"""Add labeled calibration, promotion decisions, and false-positive reports.

Revision ID: 0013_model_governance
Revises: 0012_notifications
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_model_governance"
down_revision: str | None = "0012_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "calibration_labels",
    "model_calibrations",
    "model_promotion_decisions",
    "false_positive_reports",
)


def upgrade() -> None:
    op.create_table(
        "calibration_labels",
        sa.Column(
            "label_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("model_family", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=False),
        sa.Column("data_partition", sa.String(32), nullable=False, server_default="CALIBRATION"),
        sa.Column("segment_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("alert_id", postgresql.UUID()),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("labeled_by", sa.String(128), nullable=False),
        sa.Column("label_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "model_calibrations",
        sa.Column(
            "calibration_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "model_artifact_id",
            postgresql.UUID(),
            sa.ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("method", sa.String(32), nullable=False, server_default="PLATT"),
        sa.Column("segment_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("parameters_json", postgresql.JSONB(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "model_promotion_decisions",
        sa.Column(
            "decision_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("model_family", sa.String(128), nullable=False),
        sa.Column(
            "candidate_artifact_id",
            postgresql.UUID(),
            sa.ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "champion_artifact_id",
            postgresql.UUID(),
            sa.ForeignKey("model_artifacts.model_artifact_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "calibration_id",
            postgresql.UUID(),
            sa.ForeignKey("model_calibrations.calibration_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("checks_json", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "false_positive_reports",
        sa.Column(
            "report_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("alert_id", postgresql.UUID()),
        sa.Column("model_family", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64)),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("reported_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _indexes_and_policies()


def _indexes_and_policies() -> None:
    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        context_absent = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"
        tenant_match = "tenant_id = current_setting('app.tenant_id', true)"
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
            USING ({context_absent} OR {tenant_match})
            WITH CHECK ({context_absent} OR {tenant_match})'''
        )
    op.create_index("ix_calibration_labels_model_family", "calibration_labels", ["model_family"])
    op.create_index("ix_calibration_labels_alert_id", "calibration_labels", ["alert_id"])
    op.create_index(
        "ix_model_promotion_decisions_model_family", "model_promotion_decisions", ["model_family"]
    )
    op.create_index(
        "ix_false_positive_reports_model_family", "false_positive_reports", ["model_family"]
    )
    op.create_index("ix_false_positive_reports_alert_id", "false_positive_reports", ["alert_id"])
    op.create_index("ix_false_positive_reports_asset_id", "false_positive_reports", ["asset_id"])
    op.create_index(
        "ix_false_positive_reports_reason_code", "false_positive_reports", ["reason_code"]
    )
    op.create_index("ix_false_positive_reports_status", "false_positive_reports", ["status"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
