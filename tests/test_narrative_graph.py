from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from scam2market.features.schemas import (
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    FeatureLineage,
    FeatureSnapshot,
    RevisionState,
)
from scam2market.narratives.clustering import DeterministicNarrativeClusterer
from scam2market.narratives.embeddings import (
    DeterministicHashEmbedding,
    InMemoryVectorIndex,
)
from scam2market.narratives.graph import InMemoryCoordinationGraphProjector
from scam2market.narratives.repository import InMemoryNarrativeRepository
from scam2market.narratives.schemas import NarrativePost, ProjectionStatus
from scam2market.narratives.service import NarrativeIntelligenceService

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _snapshot() -> FeatureSnapshot:
    features: dict[str, float | int | None] = {name: 0.0 for name in FEATURE_NAMES}
    features.update({"data_quality_score": 1.0, "baseline_confidence": 0.8})
    return FeatureSnapshot(
        feature_window_id=uuid5(NAMESPACE_URL, "narrative-window"),
        asset_id="S2MUSDT",
        window_start=START,
        window_end=START + timedelta(minutes=5),
        interval_seconds=300,
        revision=1,
        is_final=True,
        revision_state=RevisionState.final,
        feature_schema_version=FEATURE_SCHEMA.feature_schema,
        features=features,
        lineage=FeatureLineage(
            lineage_id=uuid5(NAMESPACE_URL, "narrative-lineage"),
            source_event_ids=["post-1", "post-2", "post-3"],
            source_event_min_time=START,
            source_event_max_time=START + timedelta(seconds=20),
            source_count=3,
            source_hash="b" * 64,
        ),
    )


def _posts() -> list[NarrativePost]:
    return [
        NarrativePost(
            post_id="post-1",
            scope_id="LIVE",
            asset_id="S2MUSDT",
            author_id="author-a",
            event_time=START,
            text="S2M exchange listing partnership announced today",
            hashtags=["S2M"],
            urls=["https://example.test/listing"],
        ),
        NarrativePost(
            post_id="post-2",
            scope_id="LIVE",
            asset_id="S2MUSDT",
            author_id="author-b",
            event_time=START + timedelta(seconds=2),
            text="S2M exchange listing partnership announced today",
            hashtags=["S2M"],
            urls=["https://example.test/listing"],
            repost_of="post-1",
        ),
        NarrativePost(
            post_id="post-3",
            scope_id="LIVE",
            asset_id="S2MUSDT",
            author_id="author-c",
            event_time=START + timedelta(seconds=20),
            text="Unrelated discussion about network maintenance",
        ),
    ]


async def _run(
    posts: list[NarrativePost], *, graph_fail: bool = False
) -> tuple[InMemoryNarrativeRepository, InMemoryVectorIndex, InMemoryCoordinationGraphProjector]:
    repository = InMemoryNarrativeRepository(posts)
    index = InMemoryVectorIndex()
    projector = InMemoryCoordinationGraphProjector(fail=graph_fail)
    service = NarrativeIntelligenceService(
        repository=repository,
        embedding=DeterministicHashEmbedding(64),
        vector_index=index,
        graph_projector=projector,
        clusterer=DeterministicNarrativeClusterer(0.75),
    )
    await service.process(_snapshot())
    return repository, index, projector


async def test_embedding_metadata_and_replay_clustering_are_reproducible() -> None:
    first, index, _ = await _run(_posts())
    second, _, _ = await _run(list(reversed(_posts())))

    assert index.points["post-1"][1]["asset_id"] == "S2MUSDT"
    assert index.points["post-1"][1]["event_time"] == START.isoformat()
    assert [cluster.narrative_id for cluster in first.clusters] == [
        cluster.narrative_id for cluster in second.clusters
    ]
    assert first.clusters[0].post_ids == second.clusters[0].post_ids


async def test_graph_projection_links_posts_assets_narratives_and_computes_features() -> None:
    repository, _, projector = await _run(_posts())

    assert ("post-1", "MENTIONS", "S2MUSDT") in projector.relationships
    assert any(relation[1] == "MEMBER_OF" for relation in projector.relationships)
    assert repository.graphs[0].features.graph_score is not None
    assert repository.graphs[0].features.synchronized_posting > 0


async def test_graph_failure_is_degraded_and_does_not_discard_narratives() -> None:
    repository, _, _ = await _run(_posts(), graph_fail=True)

    assert repository.clusters
    assert repository.graphs[0].projection_status == ProjectionStatus.degraded
    assert repository.graphs[0].features.graph_score is not None
