import math
from collections import Counter
from typing import Protocol

from neo4j import AsyncDriver, AsyncGraphDatabase

from scam2market.narratives.schemas import GraphFeatures, NarrativeCluster, NarrativePost


class CoordinationGraphProjector(Protocol):
    version: str

    async def project(
        self,
        posts: list[NarrativePost],
        clusters: list[NarrativeCluster],
        *,
        campaign_id: str | None = None,
        alert_ids: list[str] | None = None,
    ) -> tuple[int, int]: ...


class GraphFeatureExtractor:
    version = "coordination-graph-features-v1"

    def compute(
        self, posts: list[NarrativePost], clusters: list[NarrativeCluster]
    ) -> GraphFeatures:
        if not posts:
            return GraphFeatures(
                community_concentration=0,
                synchronized_posting=0,
                repeated_amplifier_overlap=0,
                propagation_depth=0,
                community_entropy=0,
                cross_community_spread=0,
                node_similarity=0,
                graph_score=None,
            )
        author_counts = Counter(post.author_id for post in posts)
        concentration = max(author_counts.values()) / len(posts)
        author_total = len(author_counts)
        entropy = -sum(
            (count / len(posts)) * math.log(count / len(posts)) for count in author_counts.values()
        )
        normalized_entropy = entropy / math.log(author_total) if author_total > 1 else 0.0
        times = sorted(post.event_time for post in posts)
        synchronized = (
            sum(
                (right - left).total_seconds() <= 5
                for left, right in zip(times, times[1:], strict=False)
            )
            / (len(times) - 1)
            if len(times) > 1
            else 0.0
        )
        urls = Counter(url for post in posts for url in post.urls)
        hashtags = Counter(tag.lower() for post in posts for tag in post.hashtags)
        overlap = max(max(urls.values(), default=0), max(hashtags.values(), default=0)) / len(posts)
        depth = _propagation_depth(posts)
        time_to_10 = _time_to_author_count(posts, 10)
        time_to_100 = _time_to_author_count(posts, 100)
        spread = min(1.0, author_total / max(1.0, len(posts)))
        similarity_values = [
            similarity for cluster in clusters for similarity in cluster.similarities.values()
        ]
        node_similarity = (
            sum(similarity_values) / len(similarity_values) if similarity_values else 0.0
        )
        graph_score = min(
            1.0,
            0.22 * concentration
            + 0.20 * synchronized
            + 0.18 * overlap
            + 0.15 * min(1.0, depth / 5)
            + 0.15 * node_similarity
            + 0.10 * (1.0 - normalized_entropy),
        )
        return GraphFeatures(
            community_concentration=concentration,
            synchronized_posting=synchronized,
            repeated_amplifier_overlap=overlap,
            propagation_depth=depth,
            community_entropy=normalized_entropy,
            time_to_10_authors_seconds=time_to_10,
            time_to_100_authors_seconds=time_to_100,
            cross_community_spread=spread,
            node_similarity=node_similarity,
            graph_score=graph_score,
        )


class Neo4jCoordinationGraphProjector:
    version = "neo4j-projection-v1"

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    async def project(
        self,
        posts: list[NarrativePost],
        clusters: list[NarrativeCluster],
        *,
        campaign_id: str | None = None,
        alert_ids: list[str] | None = None,
    ) -> tuple[int, int]:
        cluster_by_post = {
            post_id: str(cluster.narrative_id)
            for cluster in clusters
            for post_id in cluster.post_ids
        }
        rows = [
            {
                "post_id": post.post_id,
                "author_id": post.author_id,
                "asset_id": post.asset_id,
                "narrative_id": cluster_by_post[post.post_id],
                "event_time": post.event_time.isoformat(),
                "reply_to": post.reply_to,
                "repost_of": post.repost_of,
                "amplifies": bool(post.repost_of or post.urls or post.hashtags),
            }
            for post in posts
        ]
        query = """
        UNWIND $posts AS item
        MERGE (actor:Actor {actor_id: item.author_id})
        MERGE (post:Post {post_id: item.post_id})
          SET post.event_time = item.event_time
        MERGE (asset:Asset {asset_id: item.asset_id})
        MERGE (narrative:Narrative {narrative_id: item.narrative_id})
        MERGE (actor)-[:POSTED]->(post)
        MERGE (post)-[:MENTIONS]->(asset)
        MERGE (post)-[:MEMBER_OF]->(narrative)
        FOREACH (_ IN CASE WHEN item.reply_to IS NULL THEN [] ELSE [1] END |
          MERGE (parent:Post {post_id: item.reply_to})
          MERGE (post)-[:REPLIES_TO]->(parent))
        FOREACH (_ IN CASE WHEN item.repost_of IS NULL THEN [] ELSE [1] END |
          MERGE (original:Post {post_id: item.repost_of})
          MERGE (post)-[:REPOSTS]->(original))
        FOREACH (_ IN CASE WHEN item.amplifies THEN [1] ELSE [] END |
          MERGE (post)-[:AMPLIFIES]->(narrative))
        FOREACH (_ IN CASE WHEN $campaign_id IS NULL THEN [] ELSE [1] END |
          MERGE (campaign:Campaign {campaign_id: $campaign_id})
          MERGE (campaign)-[:TARGETS]->(asset)
          MERGE (narrative)-[:EVIDENCE_FOR]->(campaign))
        WITH DISTINCT narrative
        UNWIND $alert_ids AS alert_id
        MERGE (alert:Alert {alert_id: alert_id})
        MERGE (alert)-[:SUPPORTED_BY]->(narrative)
        """
        await self._driver.execute_query(
            query,
            parameters_={
                "posts": rows,
                "campaign_id": campaign_id,
                "alert_ids": alert_ids or [],
            },
            database_=self._database,
        )
        actors = len({post.author_id for post in posts})
        node_count = actors + len(posts) + len(clusters) + 1
        if campaign_id:
            node_count += 1
        node_count += len(alert_ids or [])
        relationship_count = len(posts) * 3 + sum(
            bool(post.reply_to) + bool(post.repost_of) + bool(post.urls or post.hashtags)
            for post in posts
        )
        return node_count, relationship_count

    async def close(self) -> None:
        await self._driver.close()


class InMemoryCoordinationGraphProjector:
    version = "memory-projection-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.nodes: dict[str, set[str]] = {
            "Actor": set(),
            "Post": set(),
            "Asset": set(),
            "Narrative": set(),
            "Campaign": set(),
            "Alert": set(),
        }
        self.relationships: set[tuple[str, str, str]] = set()

    async def project(
        self,
        posts: list[NarrativePost],
        clusters: list[NarrativeCluster],
        *,
        campaign_id: str | None = None,
        alert_ids: list[str] | None = None,
    ) -> tuple[int, int]:
        if self.fail:
            raise RuntimeError("graph projection unavailable")
        cluster_by_post = {
            post_id: str(cluster.narrative_id)
            for cluster in clusters
            for post_id in cluster.post_ids
        }
        for post in posts:
            self.nodes["Actor"].add(post.author_id)
            self.nodes["Post"].add(post.post_id)
            self.nodes["Asset"].add(post.asset_id)
            narrative_id = cluster_by_post[post.post_id]
            self.nodes["Narrative"].add(narrative_id)
            self.relationships.update(
                {
                    (post.author_id, "POSTED", post.post_id),
                    (post.post_id, "MENTIONS", post.asset_id),
                    (post.post_id, "MEMBER_OF", narrative_id),
                }
            )
            if post.reply_to:
                self.relationships.add((post.post_id, "REPLIES_TO", post.reply_to))
            if post.repost_of:
                self.relationships.add((post.post_id, "REPOSTS", post.repost_of))
        if campaign_id:
            self.nodes["Campaign"].add(campaign_id)
            for post in posts:
                self.relationships.add((campaign_id, "TARGETS", post.asset_id))
        for alert_id in alert_ids or []:
            self.nodes["Alert"].add(alert_id)
            for cluster in clusters:
                self.relationships.add((alert_id, "SUPPORTED_BY", str(cluster.narrative_id)))
        return sum(map(len, self.nodes.values())), len(self.relationships)


def _time_to_author_count(posts: list[NarrativePost], target: int) -> float | None:
    first_seen: dict[str, object] = {}
    ordered = sorted(posts, key=lambda post: (post.event_time, post.post_id))
    start = ordered[0].event_time
    for post in ordered:
        first_seen.setdefault(post.author_id, post.event_time)
        if len(first_seen) >= target:
            return (post.event_time - start).total_seconds()
    return None


def _propagation_depth(posts: list[NarrativePost]) -> int:
    parents = {post.post_id: post.reply_to or post.repost_of for post in posts}

    def depth(post_id: str, seen: set[str]) -> int:
        parent = parents.get(post_id)
        if parent is None or parent not in parents or parent in seen:
            return 0
        return 1 + depth(parent, seen | {parent})

    return max((depth(post.post_id, {post.post_id}) for post in posts), default=0)
