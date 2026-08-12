"""Add official source policies, connector runs, disclosure versions, and evidence.

Revision ID: 0014_official_verification
Revises: 0013_model_governance
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_official_verification"
down_revision: str | None = "0013_model_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_policies",
        sa.Column(
            "source_policy_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_class", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("connector_type", sa.String(64), nullable=False),
        sa.Column("connector_config_json", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("trust_tier", sa.String(32), nullable=False),
        sa.Column("trust_rationale", sa.Text()),
        sa.Column("license_allowed_usages_json", postgresql.JSONB(), nullable=False),
        sa.Column("license_retention_days", sa.Integer()),
        sa.Column("license_attribution", sa.Text()),
        sa.Column(
            "license_display_allowed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("canonical_domains_json", postgresql.JSONB(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", "policy_version", name="uq_source_policy_version"),
    )
    op.create_table(
        "source_connector_runs",
        sa.Column(
            "connector_run_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_policy_id",
            postgresql.UUID(),
            sa.ForeignKey("source_policies.source_policy_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("checkpoint_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lag_seconds", sa.Float()),
        sa.Column("error_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_watermark", sa.DateTime(timezone=True)),
        sa.Column("max_staleness_seconds", sa.Integer(), nullable=False, server_default="86400"),
    )
    op.add_column(
        "disclosures",
        sa.Column(
            "source_policy_id",
            postgresql.UUID(),
            sa.ForeignKey("source_policies.source_policy_id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "disclosures",
        sa.Column(
            "connector_run_id",
            postgresql.UUID(),
            sa.ForeignKey("source_connector_runs.connector_run_id", ondelete="SET NULL"),
        ),
    )
    op.add_column("disclosures", sa.Column("source_document_key", sa.String(500)))
    op.add_column("disclosures", sa.Column("logical_source_key", sa.String(500)))
    op.execute(
        "UPDATE disclosures SET logical_source_key = source, "
        "source_document_key = source_document_id"
    )
    op.alter_column("disclosures", "logical_source_key", nullable=False)
    op.alter_column("disclosures", "source_document_key", nullable=False)
    op.drop_constraint("uq_disclosure_version", "disclosures", type_="unique")
    op.create_unique_constraint(
        "uq_disclosure_logical_version",
        "disclosures",
        ["logical_source_key", "source_document_key", "document_version"],
    )
    op.add_column(
        "disclosures",
        sa.Column("version_status", sa.String(32), nullable=False, server_default="CURRENT"),
    )
    op.add_column("disclosures", sa.Column("available_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE disclosures SET available_at = GREATEST(first_observed_at, ingested_at)")
    op.alter_column("disclosures", "available_at", nullable=False)
    op.add_column("disclosures", sa.Column("etag", sa.String(500)))
    op.add_column("disclosures", sa.Column("last_modified", sa.String(255)))
    op.add_column(
        "disclosures",
        sa.Column(
            "signature_metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
    )
    op.create_table(
        "verification_evidence",
        sa.Column(
            "verification_evidence_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "verification_id",
            postgresql.UUID(),
            sa.ForeignKey("claim_verifications.verification_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "disclosure_id",
            postgresql.UUID(),
            sa.ForeignKey("disclosures.disclosure_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("temporal_eligible", sa.Boolean(), nullable=False),
        sa.Column("reason_codes_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_policy_id_snapshot", postgresql.UUID()),
        sa.Column("source_policy_version_snapshot", sa.String(64), nullable=False),
        sa.Column("trust_score_snapshot", sa.Float(), nullable=False),
        sa.Column("trust_tier_snapshot", sa.String(32), nullable=False),
        sa.Column("license_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "verification_id", "disclosure_id", "relation", name="uq_verification_evidence"
        ),
    )
    for table, columns in {
        "source_connector_runs": ("source_policy_id", "status", "source_watermark"),
        "disclosures": (
            "source_policy_id",
            "connector_run_id",
            "source_document_key",
            "logical_source_key",
            "available_at",
        ),
        "verification_evidence": ("verification_id", "disclosure_id"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("verification_evidence")
    op.drop_constraint("uq_disclosure_logical_version", "disclosures", type_="unique")
    op.create_unique_constraint(
        "uq_disclosure_version",
        "disclosures",
        ["source", "source_document_id", "document_version"],
    )
    for column in (
        "signature_metadata_json",
        "last_modified",
        "etag",
        "available_at",
        "version_status",
        "source_document_key",
        "logical_source_key",
        "connector_run_id",
        "source_policy_id",
    ):
        op.drop_column("disclosures", column)
    op.drop_table("source_connector_runs")
    op.drop_table("source_policies")
