from datetime import UTC, datetime

from scam2market.ingestion.archive import InMemoryRawEventArchive
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.repositories import InMemorySocialRepository
from scam2market.ingestion.social import (
    AssetMentionResolver,
    AssetRegistry,
    AuthorPseudonymizer,
    RawSocialPost,
    SocialIngestionService,
    SocialReplayProvider,
    parse_social_post,
)
from scam2market.schemas.domain import Asset, AssetType
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
    InMemorySocialRepository,
    InMemoryRawEventArchive,
    InMemoryStateStore,
]:
    repository = InMemorySocialRepository()
    archive = InMemoryRawEventArchive()
    state = InMemoryStateStore()
    service = SocialIngestionService(
        repository=repository,
        dedupe=state,
        state=state,
        archive=archive,
        publisher=InMemoryEventPublisher(),
        quality=SourceQualityTracker(300),
        pseudonymizer=AuthorPseudonymizer("test-secret-at-least-16-characters"),
        resolver=AssetMentionResolver(AssetRegistry([_asset("S2M")])),
    )
    return service, repository, archive, state


def test_ambiguous_bare_symbol_is_not_silently_mapped() -> None:
    resolver = AssetMentionResolver(AssetRegistry([_asset("ONE")], ambiguous_aliases={"ONE"}))

    mention = resolver.resolve("post-1", "ONE could move today")[0]

    assert mention.asset_id is None
    assert mention.resolution_status == "AMBIGUOUS"
    assert mention.candidate_asset_ids == ["ONEUSDT"]
    assert mention.resolver_version == "asset-resolver-v1"


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


async def test_duplicate_social_post_does_not_double_count_and_archive_is_sanitized() -> None:
    provider = SocialReplayProvider([_raw()], source="test-social", clock=lambda: NOW)
    event = [item async for item in provider.stream()][0]
    service, repository, archive, state = _service()

    assert await service.ingest(event) is True
    assert await service.ingest(event) is False
    assert len(repository.posts) == 1
    assert len(repository.mentions) == 1
    assert "raw_author_id" not in archive.events[0][1].payload
    latest = await state.get_json("latest:social:synthetic")
    assert latest is not None
