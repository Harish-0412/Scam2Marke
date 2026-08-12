"""Add durable feature-worker state checkpoints.

Revision ID: 0011_live_checkpoints
Revises: 0010_auth_rbac
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_live_checkpoints"
down_revision: str | None = "0010_auth_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "event_ingestion_log",
        "source_sequence",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
    )
    op.add_column("worker_checkpoints", sa.Column("state_json", postgresql.JSONB()))
    op.add_column("worker_checkpoints", sa.Column("state_checksum", sa.String(64)))
    op.add_column("worker_checkpoints", sa.Column("event_time", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("worker_checkpoints", "event_time")
    op.drop_column("worker_checkpoints", "state_checksum")
    op.drop_column("worker_checkpoints", "state_json")
    op.alter_column(
        "event_ingestion_log",
        "source_sequence",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
    )
