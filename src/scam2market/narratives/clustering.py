import hashlib
import math
import re
from collections import Counter
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from scam2market.narratives.embeddings import cosine_similarity
from scam2market.narratives.schemas import NarrativeCluster, NarrativePost

_WORD = re.compile(r"[a-z0-9][a-z0-9_-]+")
_STOPWORDS = {
    "about",
    "after",
    "again",
    "asset",
    "from",
    "have",
    "into",
    "just",
    "more",
    "that",
    "this",
    "with",
    "will",
}


class DeterministicNarrativeClusterer:
    version = "narrative-cluster-v1"

    def __init__(self, similarity_threshold: float = 0.76) -> None:
        self._threshold = similarity_threshold

    def cluster(
        self,
        posts: list[NarrativePost],
        *,
        window_start: datetime,
        window_end: datetime,
        embedding_version: str,
    ) -> list[NarrativeCluster]:
        ordered = sorted(posts, key=lambda item: item.post_id)
        parents = list(range(len(ordered)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[max(left_root, right_root)] = min(left_root, right_root)

        for left in range(len(ordered)):
            for right in range(left + 1, len(ordered)):
                if (
                    cosine_similarity(ordered[left].vector, ordered[right].vector)
                    >= self._threshold
                ):
                    union(left, right)

        groups: dict[int, list[NarrativePost]] = {}
        for index, post in enumerate(ordered):
            groups.setdefault(find(index), []).append(post)

        clusters = [
            self._materialize(
                group,
                window_start=window_start,
                window_end=window_end,
                embedding_version=embedding_version,
            )
            for _, group in sorted(groups.items())
        ]
        return sorted(clusters, key=lambda item: str(item.narrative_id))

    def _materialize(
        self,
        posts: list[NarrativePost],
        *,
        window_start: datetime,
        window_end: datetime,
        embedding_version: str,
    ) -> NarrativeCluster:
        post_ids = sorted(post.post_id for post in posts)
        cluster_key = hashlib.sha256("|".join(post_ids).encode()).hexdigest()
        first = posts[0]
        narrative_id = uuid5(
            NAMESPACE_URL,
            f"narrative:{first.scope_id}:{first.asset_id}:{window_start.isoformat()}:{cluster_key}",
        )
        dimensions = len(posts[0].vector)
        centroid = [
            sum(post.vector[index] for post in posts) / len(posts) for index in range(dimensions)
        ]
        norm = math.sqrt(sum(value * value for value in centroid))
        if norm:
            centroid = [value / norm for value in centroid]
        similarities = {post.post_id: cosine_similarity(post.vector, centroid) for post in posts}
        terms = Counter(
            token
            for post in posts
            for token in _WORD.findall(post.text.lower())
            if len(token) > 3 and token not in _STOPWORDS
        )
        label_terms = [
            term for term, _ in sorted(terms.items(), key=lambda item: (-item[1], item[0]))[:4]
        ]
        label = " / ".join(label_terms) if label_terms else f"{first.asset_id} discussion"
        summary_parts = [
            post.text.strip() for post in sorted(posts, key=lambda item: item.post_id)[:3]
        ]
        summary = " ".join(summary_parts)[:1000]
        return NarrativeCluster(
            narrative_id=narrative_id,
            cluster_key=cluster_key,
            scope_id=first.scope_id,
            asset_id=first.asset_id,
            window_start=window_start,
            window_end=window_end,
            label=label,
            summary=summary,
            post_ids=post_ids,
            similarities=similarities,
            unique_author_count=len({post.author_id for post in posts}),
            centroid=centroid,
            embedding_version=embedding_version,
        )
