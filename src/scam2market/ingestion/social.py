import asyncio
import hashlib
import hmac
import re
import unicodedata
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from scam2market.common.time import utc_now
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.schemas.domain import Asset, AssetMention, SocialPost
from scam2market.schemas.events import CanonicalEvent, EventType, ReplayMetadata, TraceMetadata
from scam2market.state import DedupeStore, OnlineStateStore
from scam2market.streaming.publisher import CanonicalEventPublisher

HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{0,31})")
CASHTAG_RE = re.compile(r"(?<!\w)\$([A-Za-z][A-Za-z0-9]{0,15})")
USER_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_]{1,32})")
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


class RawSocialPost(BaseModel):
    source_post_id: str
    platform: str
    raw_author_id: str
    event_time: datetime
    text: str
    language: str | None = None
    reply_to: str | None = None
    repost_of: str | None = None
    engagement: dict[str, int | float] = Field(default_factory=dict)


class SocialProvider(Protocol):
    source: str

    def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]: ...


class SocialReplayProvider:
    def __init__(
        self,
        records: Sequence[RawSocialPost],
        *,
        source: str = "social-replay",
        speed_multiplier: float = 0.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if speed_multiplier < 0:
            raise ValueError("speed_multiplier cannot be negative")
        self.source = source
        self._records = sorted(records, key=lambda post: (post.event_time, post.source_post_id))
        self._speed_multiplier = speed_multiplier
        self._clock = clock

    async def stream(self, replay_session_id: str | None = None) -> AsyncIterator[CanonicalEvent]:
        previous_time: datetime | None = None
        session_id = replay_session_id or "standalone"
        for sequence, post in enumerate(self._records, start=1):
            if self._speed_multiplier > 0 and previous_time is not None:
                delay = (post.event_time - previous_time).total_seconds() / self._speed_multiplier
                if delay > 0:
                    await asyncio.sleep(delay)
            yield CanonicalEvent(
                event_id=str(
                    uuid5(NAMESPACE_URL, f"{self.source}:{session_id}:{post.source_post_id}")
                ),
                origin_event_id=f"{self.source}:{post.source_post_id}",
                delivery_event_id=str(
                    uuid5(NAMESPACE_URL, f"{self.source}:{session_id}:{post.source_post_id}")
                ),
                event_type=EventType.social_post_received,
                schema_version=1,
                source=self.source,
                source_event_id=post.source_post_id,
                source_sequence=sequence,
                event_time=post.event_time,
                ingested_at=post.event_time if replay_session_id is not None else self._clock(),
                partition_key=post.platform,
                replay=ReplayMetadata(
                    is_replay=replay_session_id is not None,
                    replay_session_id=replay_session_id,
                ),
                payload=post.model_dump(mode="json"),
            )
            previous_time = post.event_time


class SyntheticSocialProvider(SocialReplayProvider):
    def __init__(
        self,
        *,
        source: str = "synthetic-social-v1",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        texts = [
            "$S2M is starting to move. Watch the volume. https://promo.example/s2m",
            "Big announcement soon for #S2M https://promo.example/s2m",
            "$S2M breakout incoming https://promo.example/s2m",
            "Everyone is talking about $S2M https://promo.example/s2m",
            "Repost: $S2M target 2x https://promo.example/s2m",
            "$S2M volume just exploded https://promo.example/s2m",
        ]
        records = [
            RawSocialPost(
                source_post_id=f"synthetic-post-{index:03d}",
                platform="synthetic",
                raw_author_id=f"actor-{index % 2}",
                event_time=start + timedelta(seconds=index * 30),
                text=text,
                repost_of="synthetic-post-000" if index > 0 else None,
            )
            for index, text in enumerate(texts)
        ]
        super().__init__(records, source=source, clock=clock)


class AuthorPseudonymizer:
    def __init__(self, secret: str, *, key_version: int = 1) -> None:
        if len(secret) < 16:
            raise ValueError("pseudonymization secret must contain at least 16 characters")
        self._secret = secret.encode("utf-8")
        self.key_version = key_version

    def pseudonymize(self, platform: str, raw_author_id: str) -> str:
        digest = hmac.new(
            self._secret,
            f"{platform}:{raw_author_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"actor_{digest[:32]}"


@dataclass(frozen=True, slots=True)
class AliasCandidate:
    asset_id: str
    symbol: str
    is_ambiguous: bool


class AssetRegistry:
    def __init__(self, assets: Sequence[Asset], ambiguous_aliases: set[str] | None = None) -> None:
        ambiguous = {alias.upper() for alias in (ambiguous_aliases or set())}
        self._aliases: dict[str, list[AliasCandidate]] = {}
        for asset in assets:
            symbol = asset.symbol.upper()
            candidate = AliasCandidate(asset.asset_id, symbol, symbol in ambiguous)
            self._aliases.setdefault(symbol, []).append(candidate)
            normalized_name = unicodedata.normalize("NFKC", asset.name).strip().upper()
            if normalized_name and normalized_name != symbol:
                self._aliases.setdefault(normalized_name, []).append(candidate)

    def candidates(self, alias: str) -> list[AliasCandidate]:
        return list(self._aliases.get(alias.upper(), []))

    @property
    def aliases(self) -> set[str]:
        return set(self._aliases)


class AssetMentionResolver:
    def __init__(
        self,
        registry: AssetRegistry,
        *,
        version: str = "asset-resolver-v1",
    ) -> None:
        self._registry = registry
        self.version = version

    def resolve(self, post_id: str, text: str) -> list[AssetMention]:
        normalized_text = unicodedata.normalize("NFKC", text)
        matches: dict[tuple[int, int], tuple[str, str]] = {}
        for kind, pattern in (("CASHTAG", CASHTAG_RE), ("HASHTAG", HASHTAG_RE)):
            for match in pattern.finditer(normalized_text):
                matches[(match.start(), match.end())] = (match.group(1), kind)
        for alias in sorted(self._registry.aliases, key=len, reverse=True):
            pattern = re.compile(rf"(?<![\w$#]){re.escape(alias)}(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(normalized_text):
                matches.setdefault((match.start(), match.end()), (match.group(0), "BARE"))

        resolved: list[AssetMention] = []
        for (start, end), (alias, kind) in sorted(matches.items()):
            candidates = self._registry.candidates(alias)
            candidate_ids = [candidate.asset_id for candidate in candidates]
            context_start = max(0, start - 24)
            context_end = min(len(normalized_text), end + 24)
            context = normalized_text[context_start:context_end].upper()
            has_market_context = any(
                token in context for token in (" STOCK", " TOKEN", " COIN", " CRYPTO", " SHARES")
            )
            ambiguous = len(candidates) > 1 or any(
                candidate.is_ambiguous for candidate in candidates
            )
            explicit = kind == "CASHTAG"
            if not candidates:
                asset_id = None
                status = "UNRESOLVED"
                confidence = 0.0
                reason = "ALIAS_NOT_IN_REGISTRY"
            elif ambiguous and not explicit and not (has_market_context and len(candidates) == 1):
                asset_id = None
                status = "AMBIGUOUS"
                confidence = 0.4 if kind == "BARE" else 0.6
                reason = "AMBIGUOUS_ALIAS_WITHOUT_MARKET_CONTEXT"
            elif len(candidates) > 1:
                asset_id = None
                status = "AMBIGUOUS"
                confidence = 0.7
                reason = "MULTIPLE_EXACT_CANDIDATES"
            else:
                asset_id = candidates[0].asset_id
                status = "RESOLVED"
                confidence = (
                    0.88
                    if has_market_context and kind == "BARE"
                    else {"CASHTAG": 0.98, "HASHTAG": 0.82, "BARE": 0.62}[kind]
                )
                reason = (
                    "EXACT_CASHTAG"
                    if kind == "CASHTAG"
                    else "MARKET_CONTEXT_ALIAS"
                    if has_market_context
                    else "UNIQUE_REGISTRY_ALIAS"
                )
            resolved.append(
                AssetMention(
                    post_id=post_id,
                    asset_id=asset_id,
                    mention_text=text[start:end],
                    start_offset=start,
                    end_offset=end,
                    confidence=confidence,
                    resolver_version=self.version,
                    resolution_status=status,
                    candidate_asset_ids=candidate_ids,
                    resolution_reason=reason,
                )
            )
        return resolved


def parse_social_post(
    raw: RawSocialPost,
    *,
    source: str,
    pseudonymizer: AuthorPseudonymizer,
    scope_id: str = "LIVE",
) -> SocialPost:
    normalized_text = unicodedata.normalize("NFKC", raw.text)
    return SocialPost(
        post_id=str(uuid5(NAMESPACE_URL, f"social-post:{scope_id}:{source}:{raw.source_post_id}")),
        platform=raw.platform,
        author_id=pseudonymizer.pseudonymize(raw.platform, raw.raw_author_id),
        pseudonym_key_version=pseudonymizer.key_version,
        event_time=raw.event_time,
        text=normalized_text,
        language=raw.language,
        hashtags=[match.group(1).upper() for match in HASHTAG_RE.finditer(normalized_text)],
        cashtags=[match.group(1).upper() for match in CASHTAG_RE.finditer(normalized_text)],
        user_mentions=[match.group(1) for match in USER_MENTION_RE.finditer(normalized_text)],
        urls=[match.group(0).rstrip(".,;:!?") for match in URL_RE.finditer(normalized_text)],
        reply_to=raw.reply_to,
        repost_of=raw.repost_of,
        engagement=raw.engagement,
        source_metadata={"source": source, "source_post_id": raw.source_post_id},
    )


class SocialIngestionService:
    def __init__(
        self,
        *,
        dedupe: DedupeStore,
        state: OnlineStateStore,
        publisher: CanonicalEventPublisher,
        quality: SourceQualityTracker,
        pseudonymizer: AuthorPseudonymizer,
        resolver: AssetMentionResolver,
    ) -> None:
        self._dedupe = dedupe
        self._state = state
        self._publisher = publisher
        self._quality = quality
        self._pseudonymizer = pseudonymizer
        self._resolver = resolver

    async def ingest(self, event: CanonicalEvent) -> bool:
        if event.event_type != EventType.social_post_received:
            raise ValueError(f"unsupported social event type: {event.event_type}")
        raw = RawSocialPost.model_validate(event.payload)
        dedupe_key = event.dedupe_key()
        if not await self._dedupe.claim(dedupe_key):
            return False
        post = parse_social_post(
            raw,
            source=event.source,
            pseudonymizer=self._pseudonymizer,
            scope_id=event.replay.replay_session_id or "LIVE",
        )
        mentions = self._resolver.resolve(post.post_id, post.text)
        sanitized_payload = raw.model_dump(mode="json", exclude={"raw_author_id"})
        sanitized_payload["pseudonymous_author_id"] = post.author_id
        sanitized_payload["pseudonym_key_version"] = post.pseudonym_key_version
        safe_raw_event = event.model_copy(update={"payload": sanitized_payload})
        normalized_event = CanonicalEvent(
            event_id=str(uuid5(NAMESPACE_URL, f"{event.event_id}:normalized")),
            event_type=EventType.social_post_normalized,
            schema_version=1,
            source=event.source,
            source_event_id=f"{event.source_event_id}:normalized",
            origin_event_id=f"{event.origin_event_id}:normalized",
            delivery_event_id=str(uuid5(NAMESPACE_URL, f"{event.event_id}:normalized")),
            source_sequence=event.source_sequence,
            event_time=event.event_time,
            ingested_at=event.ingested_at,
            processed_at=utc_now(),
            partition_key=post.post_id,
            replay=event.replay,
            trace=TraceMetadata(
                correlation_id=event.trace.correlation_id, causation_id=event.event_id
            ),
            payload=post.model_dump(mode="json"),
        )
        mention_event = CanonicalEvent(
            event_id=str(uuid5(NAMESPACE_URL, f"{event.event_id}:mentions")),
            event_type=EventType.social_asset_mention_detected,
            schema_version=1,
            source=event.source,
            source_event_id=f"{event.source_event_id}:mentions",
            origin_event_id=f"{event.origin_event_id}:mentions",
            delivery_event_id=str(uuid5(NAMESPACE_URL, f"{event.event_id}:mentions")),
            source_sequence=event.source_sequence,
            asset_id=next((mention.asset_id for mention in mentions if mention.asset_id), None),
            event_time=event.event_time,
            ingested_at=event.ingested_at,
            processed_at=utc_now(),
            partition_key=post.post_id,
            replay=event.replay,
            trace=TraceMetadata(
                correlation_id=event.trace.correlation_id, causation_id=normalized_event.event_id
            ),
            payload={"post_id": post.post_id, "mentions": [item.model_dump() for item in mentions]},
        )
        published_events = (
            ("social.posts.raw.v1", safe_raw_event),
            ("social.posts.normalized.v1", normalized_event),
            ("social.mentions.v1", mention_event),
        )
        try:
            await self._publisher.publish_batch(published_events)
            quality = self._quality.observe(
                source=event.source,
                asset_id=post.platform,
                event_time=post.event_time,
                ingested_at=event.ingested_at,
                sequence=event.source_sequence,
            )
            await self._state.set_json(
                f"latest:social:{post.platform}",
                {
                    "post": post.model_dump(mode="json"),
                    "mentions": [mention.model_dump(mode="json") for mention in mentions],
                },
            )
            await self._state.set_json(
                f"source-health:social:{event.source}:{post.platform}", quality.as_dict()
            )
            return True
        except Exception:
            await self._dedupe.release(dedupe_key)
            raise

    async def run_provider(
        self, provider: SocialProvider, replay_session_id: str | None = None
    ) -> int:
        accepted = 0
        async for event in provider.stream(replay_session_id):
            accepted += int(await self.ingest(event))
        return accepted
