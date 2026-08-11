"""Add scope_id column to campaign_evidence table for Phase 8 corrections."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_add_scope_id"
down_revision = "0005_phase_8_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add scope_id column (non-nullable, default "LIVE")
    op.add_column(
        "campaign_evidence",
        sa.Column(
            "scope_id",
            sa.String(128),
            nullable=False,
            server_default=sa.text("'LIVE'"),
        ),
    )
    # Create index for scope_id
    op.create_index(
        "ix_campaign_evidence_scope_id",
        "campaign_evidence",
        ["scope_id"],
    )
    # Remove server default after backfill (optional, keep for now)
    op.alter_column(
        "campaign_evidence",
        "scope_id",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_evidence_scope_id", table_name="campaign_evidence")
    op.drop_column("campaign_evidence", "scope_id")
