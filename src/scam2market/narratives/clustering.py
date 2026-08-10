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
    version = "narrative-cluster-v2-centroid-coherent"

    def __init__(
        self,
        similarity_threshold: float = 0.76,
        minimum_exemplar_similarity: float = 0.68,
    ) -> None:
        self._threshold = similarity_threshold
        self._minimum_exemplar_similarity = minimum_exemplar_similarity

    def cluster(
        self,
        posts: list[NarrativePost],
        *,
        window_start: datetime,
        window_end: datetime,
        embedding_version: str,
    ) -> list[NarrativeCluster]:
        ordered = sorted(posts, key=lambda item: (item.event_time, item.post_id))
        groups: list[list[NarrativePost]] = []
        for post in ordered:
            candidates: list[tuple[float, str, int]] = []
            for index, group in enumerate(groups):
                centroid = _centroid(group)
                centroid_similarity = cosine_similarity(post.vector, centroid)
                minimum_similarity = min(
                    cosine_similarity(post.vector, member.vector) for member in group
                )
                if (
                    centroid_similarity >= self._threshold
                    and minimum_similarity >= self._minimum_exemplar_similarity
                ):
                    seed = min(group, key=lambda item: (item.event_time, item.post_id)).post_id
                    candidates.append((centroid_similarity, seed, index))
            if candidates:
                _, _, selected = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
                groups[selected].append(post)
            else:
                groups.append([post])

        clusters = [
            self._materialize(
                group,
                window_start=window_start,
                window_end=window_end,
                embedding_version=embedding_version,
            )
            for group in groups
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
        member_hash = hashlib.sha256("|".join(post_ids).encode()).hexdigest()
        first = min(posts, key=lambda item: (item.event_time, item.post_id))
        stable_key = f"{window_start.isoformat()}:{first.post_id}:{self.version}"
        narrative_id = uuid5(
            NAMESPACE_URL,
            f"narrative:{first.scope_id}:{first.asset_id}:{stable_key}",
        )
        narrative_revision_id = uuid5(
            NAMESPACE_URL, f"narrative-revision:{narrative_id}:{member_hash}"
        )
        centroid = _centroid(posts)
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
            narrative_revision_id=narrative_revision_id,
            cluster_key=member_hash,
            stable_key=stable_key,
            member_hash=member_hash,
            scope_id=first.scope_id,
            asset_id=first.asset_id,
            window_start=window_start,
            window_end=window_end,
            first_seen=min(post.event_time for post in posts),
            last_seen=max(post.event_time for post in posts),
            label=label,
            summary=summary,
            post_ids=post_ids,
            similarities=similarities,
            unique_author_count=len({post.author_id for post in posts}),
            centroid=centroid,
            embedding_version=embedding_version,
        )


def _centroid(posts: list[NarrativePost]) -> list[float]:
    dimensions = len(posts[0].vector)
    centroid = [
        sum(post.vector[index] for post in posts) / len(posts) for index in range(dimensions)
    ]
    norm = math.sqrt(sum(value * value for value in centroid))
    return [value / norm for value in centroid] if norm else centroid
