from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from scam2market.features.schemas import FeatureSnapshot
from scam2market.narratives.clustering import DeterministicNarrativeClusterer
from scam2market.narratives.embeddings import EmbeddingProvider, VectorIndex
from scam2market.narratives.graph import CoordinationGraphProjector, GraphFeatureExtractor
from scam2market.narratives.repository import NarrativeRepository
from scam2market.narratives.schemas import GraphSnapshot, ProjectionStatus
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata


class NarrativeIntelligenceService:
    def __init__(
        self,
        *,
        repository: NarrativeRepository,
        embedding: EmbeddingProvider,
        vector_index: VectorIndex,
        graph_projector: CoordinationGraphProjector,
        clusterer: DeterministicNarrativeClusterer | None = None,
        graph_features: GraphFeatureExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._embedding = embedding
        self._index = vector_index
        self._projector = graph_projector
        self._clusterer = clusterer or DeterministicNarrativeClusterer()
        self._features = graph_features or GraphFeatureExtractor()

    async def process(self, snapshot: FeatureSnapshot) -> GraphSnapshot | None:
        posts = await self._repository.posts_for_window(snapshot)
        if not posts:
            return None
        indexing_errors: list[str] = []
        for post in posts:
            post.vector = await self._embedding.embed(post.text)
        clusters = self._clusterer.cluster(
            posts,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            embedding_version=self._embedding.version,
        )
        clusters = [
            cluster.model_copy(update={"revision": snapshot.revision}) for cluster in clusters
        ]
        revision_by_post = {
            post_id: str(cluster.narrative_revision_id)
            for cluster in clusters
            for post_id in cluster.post_ids
        }
        for post in posts:
            try:
                await self._index.upsert(
                    post.post_id,
                    post.vector,
                    {
                        "post_id": post.post_id,
                        "scope_id": post.scope_id,
                        "asset_id": post.asset_id,
                        "event_time": post.event_time.isoformat(),
                        "source": post.source,
                        "platform": post.platform,
                        "language": post.language,
                        "ingested_at": (post.ingested_at.isoformat() if post.ingested_at else None),
                        "embedding_version": self._embedding.version,
                        "narrative_revision_id": revision_by_post[post.post_id],
                    },
                )
            except Exception as error:
                indexing_errors.append(f"vector index: {error!r}")
        features = self._features.compute(posts, clusters, cutoff_event_time=snapshot.window_end)
        errors = list(indexing_errors)
        component_statuses = {
            "embedding_provider_status": "HEALTHY",
            "qdrant_status": "DEGRADED" if indexing_errors else "HEALTHY",
            "neo4j_status": "HEALTHY",
            "deterministic_feature_status": "HEALTHY",
            "graph_score_status": "AVAILABLE" if features.graph_score is not None else "MISSING",
        }
        campaign_id, alert_ids = await self._repository.campaign_context(snapshot)
        try:
            node_count, relationship_count = await self._projector.project(
                posts,
                clusters,
                cutoff_event_time=snapshot.window_end,
                campaign_id=campaign_id,
                alert_ids=alert_ids,
            )
        except Exception as error:
            errors.append(f"graph projection: {error!r}")
            component_statuses["neo4j_status"] = "DEGRADED"
            node_count, relationship_count = 0, 0
        computed_at = datetime.now(tz=UTC)
        graph = GraphSnapshot(
            graph_snapshot_id=uuid5(
                NAMESPACE_URL,
                f"graph:{snapshot.scope_id}:{snapshot.feature_window_id}:{snapshot.revision}",
            ),
            scope_id=snapshot.scope_id,
            asset_id=snapshot.asset_id,
            feature_window_id=snapshot.feature_window_id,
            feature_revision=snapshot.revision,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            cutoff_event_time=snapshot.window_end,
            source_lineage_hash=snapshot.lineage.source_hash,
            projection_version=self._projector.version,
            projection_status=(ProjectionStatus.degraded if errors else ProjectionStatus.complete),
            node_count=node_count,
            relationship_count=relationship_count,
            error_message="; ".join(errors)[:2000] or None,
            component_statuses=component_statuses,
            features=features,
            computed_at=computed_at,
        )
        events = [
            (
                "narrative.events.v1",
                _event(
                    snapshot,
                    EventType.narrative_clustered,
                    f"narrative-revision:{cluster.narrative_revision_id}",
                    {
                        "narrative": cluster.model_dump(mode="json"),
                        "feature_snapshot": snapshot.model_dump(mode="json"),
                        "graph_features": features.model_dump(mode="json"),
                        "graph_snapshot_id": str(graph.graph_snapshot_id),
                    },
                    computed_at,
                ),
            )
            for cluster in clusters
        ]
        events.append(
            (
                "graph.features.v1",
                _event(
                    snapshot,
                    EventType.graph_features_computed,
                    f"graph:{graph.graph_snapshot_id}",
                    {
                        **graph.model_dump(mode="json"),
                        "feature_snapshot": snapshot.model_dump(mode="json"),
                    },
                    computed_at,
                ),
            )
        )
        await self._repository.persist(snapshot, clusters, graph, events)
        return graph


def _event(
    snapshot: FeatureSnapshot,
    event_type: EventType,
    source_event_id: str,
    payload: dict[str, object],
    now: datetime,
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                f"{event_type.value}:{snapshot.scope_id}:{source_event_id}:{snapshot.revision}",
            )
        ),
        event_type=event_type,
        schema_version=1,
        source="narrative-intelligence-v1",
        source_event_id=source_event_id,
        asset_id=snapshot.asset_id,
        event_time=snapshot.window_end,
        ingested_at=now,
        processed_at=now,
        partition_key=snapshot.asset_id,
        replay=ReplayMetadata(
            is_replay=snapshot.scope_id != "LIVE",
            replay_session_id=(snapshot.scope_id if snapshot.scope_id != "LIVE" else None),
        ),
        payload=payload,
    )
