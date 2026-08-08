"""market/social ingestion, feature windows, and fusion tables

Revision ID: 0002_ingestion_features
Revises: 0001_phase_1
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ingestion_features"
down_revision: str | None = "0001_phase_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column(
            "outbox_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("partition_key", sa.String(128), nullable=False),
        sa.Column("envelope_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["event_ingestion_log.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("outbox_id"),
        sa.UniqueConstraint("event_id", "topic", name="uq_event_outbox_event_topic"),
    )
    op.create_index("ix_event_outbox_event_id", "event_outbox", ["event_id"])
    op.create_index("ix_event_outbox_topic", "event_outbox", ["topic"])
    op.create_index("ix_event_outbox_status", "event_outbox", ["status"])

    op.create_table(
        "market_trades",
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("trade_id", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("side", sa.String(16), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replay_session_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("scope_id", "event_time", "source", "trade_id"),
    )
    op.create_index("ix_market_trades_asset_id", "market_trades", ["asset_id"])
    op.create_index("ix_market_trades_replay_session_id", "market_trades", ["replay_session_id"])

    op.create_table(
        "market_candles",
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("candle_id", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replay_session_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("scope_id", "event_time", "source", "candle_id"),
    )
    op.create_index("ix_market_candles_asset_id", "market_candles", ["asset_id"])
    op.create_index("ix_market_candles_replay_session_id", "market_candles", ["replay_session_id"])

    op.create_table(
        "orderbook_snapshots",
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("update_id", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("best_bid", sa.Float(), nullable=True),
        sa.Column("best_ask", sa.Float(), nullable=True),
        sa.Column("bids_json", postgresql.JSONB(), nullable=False),
        sa.Column("asks_json", postgresql.JSONB(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replay_session_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("scope_id", "event_time", "source", "update_id"),
    )
    op.create_index("ix_orderbook_snapshots_asset_id", "orderbook_snapshots", ["asset_id"])
    op.create_index(
        "ix_orderbook_snapshots_replay_session_id",
        "orderbook_snapshots",
        ["replay_session_id"],
    )

    op.create_table(
        "orderbook_features",
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("top_n_depth", sa.Float(), nullable=True),
        sa.Column("imbalance", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("scope_id", "event_time", "source", "snapshot_id"),
    )
    op.create_index("ix_orderbook_features_asset_id", "orderbook_features", ["asset_id"])

    for table in (
        "market_trades",
        "market_candles",
        "orderbook_snapshots",
        "orderbook_features",
    ):
        op.execute(f"SELECT create_hypertable('{table}', 'event_time', if_not_exists => TRUE)")

    op.create_table(
        "social_posts",
        sa.Column("post_id", sa.String(64), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_post_id", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("pseudonymous_author_id", sa.String(64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("hashtags_json", postgresql.JSONB(), nullable=False),
        sa.Column("cashtags_json", postgresql.JSONB(), nullable=False),
        sa.Column("urls_json", postgresql.JSONB(), nullable=False),
        sa.Column("user_mentions_json", postgresql.JSONB(), nullable=False),
        sa.Column("reply_to", sa.String(255), nullable=True),
        sa.Column("repost_of", sa.String(255), nullable=True),
        sa.Column("engagement_json", postgresql.JSONB(), nullable=False),
        sa.Column("replay_session_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("post_id"),
        sa.UniqueConstraint(
            "scope_id",
            "source",
            "source_post_id",
            name="uq_social_post_scope_source_id",
        ),
    )
    op.create_index("ix_social_posts_scope_id", "social_posts", ["scope_id"])
    op.create_index("ix_social_posts_event_time", "social_posts", ["event_time"])
    op.create_index(
        "ix_social_posts_pseudonymous_author_id",
        "social_posts",
        ["pseudonymous_author_id"],
    )
    op.create_index("ix_social_posts_replay_session_id", "social_posts", ["replay_session_id"])

    op.create_table(
        "post_asset_mentions",
        sa.Column(
            "mention_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("post_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=True),
        sa.Column("mention_text", sa.String(64), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("resolver_version", sa.String(64), nullable=False),
        sa.Column("resolution_status", sa.String(32), nullable=False),
        sa.Column("candidate_asset_ids_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["social_posts.post_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mention_id"),
        sa.UniqueConstraint(
            "post_id",
            "start_offset",
            "end_offset",
            "resolver_version",
            name="uq_post_mention_span_resolver",
        ),
    )
    op.create_index("ix_post_asset_mentions_post_id", "post_asset_mentions", ["post_id"])
    op.create_index("ix_post_asset_mentions_asset_id", "post_asset_mentions", ["asset_id"])

    op.create_table(
        "asset_aliases",
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("alias_type", sa.String(32), nullable=False),
        sa.Column("is_ambiguous", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("alias", "asset_id", "alias_type"),
    )
    op.create_table(
        "resolver_versions",
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("version"),
    )
    op.execute(
        "INSERT INTO resolver_versions (version, status, config_json) "
        "VALUES ('asset-resolver-v1', 'ACTIVE', '{\"ambiguity_threshold\": 0.8}'::jsonb)"
    )

    op.create_table(
        "feature_windows",
        sa.Column(
            "feature_window_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("feature_schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("feature_window_id"),
        sa.UniqueConstraint(
            "scope_id",
            "asset_id",
            "window_start",
            "interval_seconds",
            name="uq_feature_window_identity",
        ),
    )
    op.create_index("ix_feature_windows_scope_id", "feature_windows", ["scope_id"])
    op.create_index("ix_feature_windows_asset_id", "feature_windows", ["asset_id"])
    op.create_index("ix_feature_windows_window_end", "feature_windows", ["window_end"])

    op.create_table(
        "feature_lineage",
        sa.Column(
            "lineage_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_event_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_event_min_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event_max_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("lineage_id"),
    )
    op.create_table(
        "feature_revisions",
        sa.Column("feature_window_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("features_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["feature_window_id"], ["feature_windows.feature_window_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["lineage_id"], ["feature_lineage.lineage_id"]),
        sa.PrimaryKeyConstraint("feature_window_id", "revision"),
    )
    op.create_table(
        "asset_baselines",
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(64), nullable=False),
        sa.Column("history_window_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("baseline_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("scope_id", "asset_id", "feature_schema_version"),
    )

    op.create_table(
        "threshold_configs",
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("thresholds_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("config_version"),
    )
    op.execute(
        "INSERT INTO threshold_configs (config_version, is_active, thresholds_json) "
        "VALUES ('fusion-thresholds-v1', TRUE, "
        '\'{"watch": 0.35, "high": 0.60, "critical": 0.80}\'::jsonb)'
    )
    op.create_table(
        "market_regimes",
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("inputs_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "event_time"),
    )
    op.create_table(
        "asset_liquidity_classes",
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("liquidity_class", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_table(
        "model_scores",
        sa.Column(
            "model_score_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("feature_window_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_revision", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("market_score", sa.Float(), nullable=True),
        sa.Column("social_score", sa.Float(), nullable=True),
        sa.Column("coordination_score", sa.Float(), nullable=True),
        sa.Column("temporal_score", sa.Float(), nullable=True),
        sa.Column("claim_risk", sa.Float(), nullable=True),
        sa.Column("legitimate_event_score", sa.Float(), nullable=True),
        sa.Column("fusion_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("missing_outputs_json", postgresql.JSONB(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feature_window_id"], ["feature_windows.feature_window_id"]),
        sa.PrimaryKeyConstraint("model_score_id"),
        sa.UniqueConstraint(
            "feature_window_id",
            "feature_revision",
            "model_version",
            name="uq_model_score_window_revision_version",
        ),
    )
    op.create_index("ix_model_scores_asset_id", "model_scores", ["asset_id"])
    op.create_index("ix_model_scores_feature_window_id", "model_scores", ["feature_window_id"])
    op.create_index("ix_model_scores_scored_at", "model_scores", ["scored_at"])


def downgrade() -> None:
    op.drop_index("ix_model_scores_scored_at", table_name="model_scores")
    op.drop_index("ix_model_scores_feature_window_id", table_name="model_scores")
    op.drop_index("ix_model_scores_asset_id", table_name="model_scores")
    op.drop_table("model_scores")
    op.drop_table("asset_liquidity_classes")
    op.drop_table("market_regimes")
    op.drop_table("threshold_configs")
    op.drop_table("asset_baselines")
    op.drop_table("feature_revisions")
    op.drop_table("feature_lineage")
    op.drop_index("ix_feature_windows_window_end", table_name="feature_windows")
    op.drop_index("ix_feature_windows_asset_id", table_name="feature_windows")
    op.drop_index("ix_feature_windows_scope_id", table_name="feature_windows")
    op.drop_table("feature_windows")
    op.drop_table("resolver_versions")
    op.drop_table("asset_aliases")
    op.drop_index("ix_post_asset_mentions_asset_id", table_name="post_asset_mentions")
    op.drop_index("ix_post_asset_mentions_post_id", table_name="post_asset_mentions")
    op.drop_table("post_asset_mentions")
    op.drop_index("ix_social_posts_replay_session_id", table_name="social_posts")
    op.drop_index("ix_social_posts_pseudonymous_author_id", table_name="social_posts")
    op.drop_index("ix_social_posts_event_time", table_name="social_posts")
    op.drop_index("ix_social_posts_scope_id", table_name="social_posts")
    op.drop_table("social_posts")
    op.drop_index("ix_orderbook_features_asset_id", table_name="orderbook_features")
    op.drop_table("orderbook_features")
    op.drop_index("ix_orderbook_snapshots_replay_session_id", table_name="orderbook_snapshots")
    op.drop_index("ix_orderbook_snapshots_asset_id", table_name="orderbook_snapshots")
    op.drop_table("orderbook_snapshots")
    op.drop_index("ix_market_candles_replay_session_id", table_name="market_candles")
    op.drop_index("ix_market_candles_asset_id", table_name="market_candles")
    op.drop_table("market_candles")
    op.drop_index("ix_market_trades_replay_session_id", table_name="market_trades")
    op.drop_index("ix_market_trades_asset_id", table_name="market_trades")
    op.drop_table("market_trades")
    op.drop_index("ix_event_outbox_status", table_name="event_outbox")
    op.drop_index("ix_event_outbox_topic", table_name="event_outbox")
    op.drop_index("ix_event_outbox_event_id", table_name="event_outbox")
    op.drop_table("event_outbox")
