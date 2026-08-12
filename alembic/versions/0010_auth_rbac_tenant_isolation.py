"""Add OIDC identities, RBAC, tenant isolation, and rotatable service keys.

Revision ID: 0010_auth_rbac
Revises: 0009_phase_11_12
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_auth_rbac"
down_revision: str | None = "0009_phase_11_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "replay_sessions",
    "audit_logs",
    "campaigns",
    "alerts",
    "investigations",
    "watchlists",
    "policy_proposals",
    "model_drift_events",
)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("settings_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO tenants (tenant_id, name) VALUES ('default', 'Default tenant') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )
    op.create_table(
        "user_memberships",
        sa.Column(
            "membership_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("roles_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "subject", name="uq_membership_tenant_subject"),
    )
    op.create_index("ix_user_memberships_tenant_id", "user_memberships", ["tenant_id"])
    op.create_index("ix_user_memberships_subject", "user_memberships", ["subject"])
    op.create_table(
        "service_accounts",
        sa.Column(
            "service_account_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("roles_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_service_accounts_tenant_id", "service_accounts", ["tenant_id"])
    op.create_table(
        "service_account_keys",
        sa.Column("key_id", sa.String(32), primary_key=True),
        sa.Column(
            "service_account_id",
            postgresql.UUID(),
            sa.ForeignKey("service_accounts.service_account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_from_key_id", sa.String(32)),
    )
    op.create_index(
        "ix_service_account_keys_service_account_id",
        "service_account_keys",
        ["service_account_id"],
    )
    op.create_table(
        "auth_events",
        sa.Column(
            "auth_event_id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("subject", sa.String(255)),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("auth_method", sa.String(32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_events_tenant_id", "auth_events", ["tenant_id"])
    op.create_index("ix_auth_events_subject", "auth_events", ["subject"])
    op.create_index("ix_auth_events_event_type", "auth_events", ["event_type"])
    op.create_index("ix_auth_events_occurred_at", "auth_events", ["occurred_at"])

    for table in TENANT_TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["tenant_id"],
            ondelete="RESTRICT",
        )
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
            USING (
                NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                OR tenant_id = current_setting('app.tenant_id', true)
            )
            WITH CHECK (
                NULLIF(current_setting('app.tenant_id', true), '') IS NULL
                OR tenant_id = current_setting('app.tenant_id', true)
            )'''
        )

    op.drop_constraint("uq_watchlist_owner_scope_name", "watchlists", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_tenant_owner_scope_name",
        "watchlists",
        ["tenant_id", "owner_id", "scope_id", "name"],
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE watchlists DROP CONSTRAINT IF EXISTS uq_watchlist_tenant_owner_scope_name"
    )
    op.execute("ALTER TABLE watchlists DROP CONSTRAINT IF EXISTS uq_watchlist_owner_scope_name")
    op.create_unique_constraint(
        "uq_watchlist_owner_scope_name",
        "watchlists",
        ["owner_id", "scope_id", "name"],
    )
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
    op.drop_table("auth_events")
    op.drop_table("service_account_keys")
    op.drop_table("service_accounts")
    op.drop_table("user_memberships")
    op.drop_table("tenants")
