"""Phase 8 corrections: add first_observed_at and retrospective_only columns.

Revision ID: 0005_phase_8_corrections
Revises: 0004_campaign_graph_verification
Create Date: 2026-08-10
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_phase_8_corrections"
down_revision = "0004_campaign_graph_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add first_observed_at column to disclosures table
    op.add_column(
        "disclosures",
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    # Create index for first_observed_at
    op.create_index(
        "ix_disclosures_first_observed_at",
        "disclosures",
        ["first_observed_at"],
    )

    # Add retrospective_only column to claim_verifications table
    op.add_column(
        "claim_verifications",
        sa.Column(
            "retrospective_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # Drop retrospective_only column
    op.drop_column("claim_verifications", "retrospective_only")
    # Drop index and column for first_observed_at
    op.drop_index("ix_disclosures_first_observed_at", table_name="disclosures")
    op.drop_column("disclosures", "first_observed_at")
