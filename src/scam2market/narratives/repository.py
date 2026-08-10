from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scam2market.db.models import (
    AlertModel,
    CampaignModel,
    EventOutboxModel,
    GraphFeatureModel,
    GraphSnapshotModel,
    NarrativeModel,
    NarrativePostModel,
    NarrativeRevisionModel,
    PostAssetMentionModel,
    SocialPostModel,
)
from scam2market.features.schemas import FeatureSnapshot
from scam2market.narratives.schemas import GraphSnapshot, NarrativeCluster, NarrativePost
from scam2market.schemas.events import CanonicalEvent


class NarrativeRepository(Protocol):
    async def campaign_context(self, snapshot: FeatureSnapshot) -> tuple[str | None, list[str]]: ...

    async def posts_for_window(self, snapshot: FeatureSnapshot) -> list[NarrativePost]: ...

    async def persist(
        self,
        snapshot: FeatureSnapshot,
        clusters: list[NarrativeCluster],
        graph: GraphSnapshot,
        events: list[tuple[str, CanonicalEvent]],
    ) -> bool: ...


class SqlNarrativeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def campaign_context(self, snapshot: FeatureSnapshot) -> tuple[str | None, list[str]]:
        async with self._sessions() as session:
            campaign = await session.scalar(
                select(CampaignModel).where(
                    CampaignModel.scope_id == snapshot.scope_id,
                    CampaignModel.asset_id == snapshot.asset_id,
                    CampaignModel.status == "ACTIVE",
                )
            )
            if campaign is None:
                return None, []
            alert_ids = (
                await session.scalars(
                    select(AlertModel.alert_id).where(
                        AlertModel.campaign_id == campaign.campaign_id
                    )
                )
            ).all()
            return str(campaign.campaign_id), [str(alert_id) for alert_id in alert_ids]

    async def posts_for_window(self, snapshot: FeatureSnapshot) -> list[NarrativePost]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.scalars(
                        select(SocialPostModel)
                        .join(
                            PostAssetMentionModel,
                            PostAssetMentionModel.post_id == SocialPostModel.post_id,
                        )
                        .where(
                            SocialPostModel.scope_id == snapshot.scope_id,
                            PostAssetMentionModel.asset_id == snapshot.asset_id,
                            SocialPostModel.event_time >= snapshot.window_start,
                            SocialPostModel.event_time < snapshot.window_end,
                        )
                        .order_by(SocialPostModel.event_time, SocialPostModel.post_id)
                    )
                )
                .unique()
                .all()
            )
        return [
            NarrativePost(
                post_id=row.post_id,
                scope_id=row.scope_id,
                asset_id=snapshot.asset_id,
                author_id=row.pseudonymous_author_id,
                event_time=row.event_time,
                text=row.text,
                platform=row.platform,
                source=row.source,
                ingested_at=row.ingested_at,
                hashtags=row.hashtags_json,
                urls=row.urls_json,
                reply_to=row.reply_to,
                repost_of=row.repost_of,
            )
            for row in rows
        ]

    async def persist(
        self,
        snapshot: FeatureSnapshot,
        clusters: list[NarrativeCluster],
        graph: GraphSnapshot,
        events: list[tuple[str, CanonicalEvent]],
    ) -> bool:
        async with self._sessions() as session, session.begin():
            if await session.get(GraphSnapshotModel, graph.graph_snapshot_id) is not None:
                return False
            for cluster in clusters:
                narrative = await session.get(NarrativeModel, cluster.narrative_id)
                if narrative is None:
                    session.add(
                        NarrativeModel(
                            narrative_id=cluster.narrative_id,
                            scope_id=cluster.scope_id,
                            asset_id=cluster.asset_id,
                            window_start=cluster.window_start,
                            window_end=cluster.window_end,
                            cluster_key=cluster.cluster_key,
                            stable_key=cluster.stable_key,
                            current_revision_id=cluster.narrative_revision_id,
                            current_revision=cluster.revision,
                            member_hash=cluster.member_hash,
                            first_seen=cluster.first_seen,
                            last_seen=cluster.last_seen,
                            label=cluster.label,
                            summary=cluster.summary,
                            post_count=len(cluster.post_ids),
                            unique_author_count=cluster.unique_author_count,
                            centroid_json=cluster.centroid,
                            embedding_version=cluster.embedding_version,
                        )
                    )
                    await session.flush()
                else:
                    narrative.label = cluster.label
                    narrative.summary = cluster.summary
                    narrative.post_count = len(cluster.post_ids)
                    narrative.unique_author_count = cluster.unique_author_count
                    narrative.centroid_json = cluster.centroid
                    narrative.embedding_version = cluster.embedding_version
                    narrative.cluster_key = cluster.cluster_key
                    narrative.member_hash = cluster.member_hash
                    narrative.last_seen = max(narrative.last_seen, cluster.last_seen)
                    if cluster.revision >= narrative.current_revision:
                        narrative.current_revision = cluster.revision
                        narrative.current_revision_id = cluster.narrative_revision_id
                revision = await session.get(
                    NarrativeRevisionModel, cluster.narrative_revision_id
                )
                if revision is None:
                    session.add(
                        NarrativeRevisionModel(
                            narrative_revision_id=cluster.narrative_revision_id,
                            narrative_id=cluster.narrative_id,
                            revision=cluster.revision,
                            member_hash=cluster.member_hash,
                            window_start=cluster.window_start,
                            cutoff_event_time=cluster.window_end,
                            label=cluster.label,
                            summary=cluster.summary,
                            centroid_json=cluster.centroid,
                            post_count=len(cluster.post_ids),
                        )
                    )
                    await session.flush()
                    session.add_all(
                        [
                            NarrativePostModel(
                                narrative_revision_id=cluster.narrative_revision_id,
                                narrative_id=cluster.narrative_id,
                                post_id=post_id,
                                similarity=cluster.similarities[post_id],
                            )
                            for post_id in cluster.post_ids
                        ]
                    )
            campaign = await session.scalar(
                select(CampaignModel)
                .where(
                    CampaignModel.scope_id == snapshot.scope_id,
                    CampaignModel.asset_id == snapshot.asset_id,
                    CampaignModel.status == "ACTIVE",
                )
                .with_for_update()
            )
            if campaign is not None and clusters:
                dominant = max(
                    clusters, key=lambda item: (len(item.post_ids), str(item.narrative_id))
                )
                campaign.dominant_narrative_id = dominant.narrative_id
            session.add(
                GraphSnapshotModel(
                    graph_snapshot_id=graph.graph_snapshot_id,
                    scope_id=graph.scope_id,
                    asset_id=graph.asset_id,
                    window_start=graph.window_start,
                    window_end=graph.window_end,
                    cutoff_event_time=graph.cutoff_event_time,
                    source_lineage_hash=graph.source_lineage_hash,
                    projection_version=graph.projection_version,
                    projection_status=graph.projection_status.value,
                    node_count=graph.node_count,
                    relationship_count=graph.relationship_count,
                    error_message=graph.error_message,
                    component_status_json=graph.component_statuses,
                )
            )
            await session.flush()
            session.add(
                GraphFeatureModel(
                    graph_snapshot_id=graph.graph_snapshot_id,
                    feature_window_id=graph.feature_window_id,
                    feature_revision=graph.feature_revision,
                    graph_score=graph.features.graph_score,
                    features_json=graph.features.model_dump(mode="json"),
                    feature_version="coordination-graph-features-v1",
                    computed_at=graph.computed_at,
                )
            )
            session.add_all(
                [
                    EventOutboxModel(
                        event_id=event.event_id,
                        topic=topic,
                        partition_key=event.partition_key,
                        envelope_json=event.model_dump(mode="json"),
                    )
                    for topic, event in events
                ]
            )
        return True


class InMemoryNarrativeRepository:
    def __init__(self, posts: list[NarrativePost] | None = None) -> None:
        self.posts = posts or []
        self.clusters: list[NarrativeCluster] = []
        self.graphs: list[GraphSnapshot] = []
        self.outbox: list[tuple[str, CanonicalEvent]] = []
        self.active_campaign_id: str | None = None
        self.active_alert_ids: list[str] = []

    async def campaign_context(self, snapshot: FeatureSnapshot) -> tuple[str | None, list[str]]:
        del snapshot
        return self.active_campaign_id, list(self.active_alert_ids)

    async def posts_for_window(self, snapshot: FeatureSnapshot) -> list[NarrativePost]:
        return [
            post
            for post in self.posts
            if post.scope_id == snapshot.scope_id
            and post.asset_id == snapshot.asset_id
            and snapshot.window_start <= post.event_time < snapshot.window_end
        ]

    async def persist(
        self,
        snapshot: FeatureSnapshot,
        clusters: list[NarrativeCluster],
        graph: GraphSnapshot,
        events: list[tuple[str, CanonicalEvent]],
    ) -> bool:
        del snapshot
        if any(item.graph_snapshot_id == graph.graph_snapshot_id for item in self.graphs):
            return False
        self.clusters.extend(clusters)
        self.graphs.append(graph)
        self.outbox.extend(events)
        return True
