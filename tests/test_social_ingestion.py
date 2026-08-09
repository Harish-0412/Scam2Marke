from datetime import UTC, datetime

from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.social import (
    AssetMentionResolver,
    AssetRegistry,
    AuthorPseudonymizer,
    RawSocialPost,
    SocialIngestionService,
    SocialReplayProvider,
    parse_social_post,
)
from scam2market.schemas.domain import Asset, AssetMention, AssetType
from scam2market.state import InMemoryStateStore
from scam2market.streaming.publisher import InMemoryEventPublisher

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_id: str | None = None) -> Asset:
    return Asset(
        asset_id=asset_id or f"{symbol}USDT",
        symbol=symbol,
        name=f"{symbol} asset",
        asset_type=AssetType.synthetic,
    )


def _raw(post_id: str = "post-1", text: str = "$S2M is moving") -> RawSocialPost:
    return RawSocialPost(
        source_post_id=post_id,
        platform="synthetic",
        raw_author_id="private-user-123",
        event_time=NOW,
        text=text,
    )


def _service() -> tuple[
    SocialIngestionService,
    InMemoryEventPublisher,
    InMemoryStateStore,
]:
    publisher = InMemoryEventPublisher()
    state = InMemoryStateStore()
    service = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(300),
        pseudonymizer=AuthorPseudonymizer("test-secret-at-least-16-characters"),
        resolver=AssetMentionResolver(AssetRegistry([_asset("S2M")])),
    )
    return service, publisher, state


def test_ambiguous_bare_symbol_is_not_silently_mapped() -> None:
    resolver = AssetMentionResolver(AssetRegistry([_asset("ONE")], ambiguous_aliases={"ONE"}))

    mention = resolver.resolve("post-1", "ONE could move today")[0]

    assert mention.asset_id is None
    assert mention.resolution_status == "AMBIGUOUS"
    assert mention.candidate_asset_ids == ["ONEUSDT"]
    assert mention.resolver_version == "asset-resolver-v1"
    assert mention.resolution_reason == "AMBIGUOUS_ALIAS_WITHOUT_MARKET_CONTEXT"


def test_explicit_cashtag_resolves_with_confidence_and_version() -> None:
    resolver = AssetMentionResolver(AssetRegistry([_asset("ONE")], ambiguous_aliases={"ONE"}))

    mention = resolver.resolve("post-1", "$ONE could move today")[0]

    assert mention.asset_id == "ONEUSDT"
    assert mention.confidence >= 0.9
    assert mention.resolver_version == "asset-resolver-v1"


def test_post_id_and_pseudonymous_actor_are_stable_without_exposing_identity() -> None:
    pseudonymizer = AuthorPseudonymizer("test-secret-at-least-16-characters")

    first = parse_social_post(_raw(), source="test", pseudonymizer=pseudonymizer)
    second = parse_social_post(_raw(), source="test", pseudonymizer=pseudonymizer)

    assert first.post_id == second.post_id
    assert first.author_id == second.author_id
    assert first.author_id.startswith("actor_")
    assert "private-user-123" not in first.author_id


def test_post_id_is_stable_within_replay_and_isolated_between_replays() -> None:
    pseudonymizer = AuthorPseudonymizer("test-secret-at-least-16-characters")

    first = parse_social_post(
        _raw(), source="test", pseudonymizer=pseudonymizer, scope_id="replay-1"
    )
    repeated = parse_social_post(
        _raw(), source="test", pseudonymizer=pseudonymizer, scope_id="replay-1"
    )
    second_replay = parse_social_post(
        _raw(), source="test", pseudonymizer=pseudonymizer, scope_id="replay-2"
    )

    assert first.post_id == repeated.post_id
    assert first.post_id != second_replay.post_id


async def test_duplicate_social_post_does_not_double_publish_and_raw_event_is_sanitized() -> None:
    provider = SocialReplayProvider([_raw()], source="test-social", clock=lambda: NOW)
    event = [item async for item in provider.stream()][0]
    service, publisher, state = _service()

    assert await service.ingest(event) is True
    assert await service.ingest(event) is False
    assert len(publisher.events) == 3
    raw_topic, raw_event = publisher.events[0]
    assert raw_topic == "social.posts.raw.v1"
    assert "raw_author_id" not in raw_event.payload
    assert raw_event.payload["pseudonym_key_version"] == 1
    latest = await state.get_json("latest:social:synthetic")
    assert latest is not None


def test_unknown_cashtag_is_retained_as_unresolved_evidence() -> None:
    resolver = AssetMentionResolver(AssetRegistry([_asset("S2M")]))

    mention = resolver.resolve("post-1", "$UNKNOWN is trending")[0]

    assert mention.asset_id is None
    assert mention.resolution_status == "UNRESOLVED"
    assert mention.resolution_reason == "ALIAS_NOT_IN_REGISTRY"


def test_retained_pre_reason_event_uses_explicit_legacy_code() -> None:
    mention = AssetMention.model_validate(
        {
            "post_id": "legacy-post",
            "asset_id": "S2MUSDT",
            "mention_text": "$S2M",
            "start_offset": 0,
            "end_offset": 4,
            "confidence": 0.9,
            "resolver_version": "asset-resolver-v0",
        }
    )

    assert mention.resolution_reason == "LEGACY_UNSPECIFIED"
