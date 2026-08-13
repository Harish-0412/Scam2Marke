import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from scam2market.db.models import (
    ModelExplanationModel,
    PostAssetMentionModel,
    SocialPostModel,
    ThreatContextSnapshotModel,
    ThreatFeedStatusModel,
    ThreatIndicatorModel,
    ThreatMatchModel,
    ThreatObservationModel,
)
from scam2market.intelligence.fusion import FusionResult, ThreatContext, ThreatContextStatus
from scam2market.intelligence.otx_client import OTXIndicator, OTXPulse
from scam2market.intelligence.threat import (
    deterministic_match_id,
    match_candidates,
    normalize_indicator,
)


class IntelligenceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def persist_explanation(self, result: FusionResult) -> bool:
        explanation = result.decision_trace.model_dump(mode="json")
        encoded = json.dumps(explanation, sort_keys=True, separators=(",", ":")).encode()
        explanation_id = uuid5(NAMESPACE_URL, f"model-explanation:{result.model_score_id}")
        async with self._sessions() as session, session.begin():
            statement = (
                insert(ModelExplanationModel)
                .values(
                    explanation_id=explanation_id,
                    model_score_id=UUID(result.model_score_id),
                    method="DETERMINISTIC_FUSION_TRACE",
                    version=result.decision_trace.version,
                    scope_id=result.scope_id,
                    explanation_json=explanation,
                    explanation_hash=hashlib.sha256(encoded).hexdigest(),
                    status="COMPLETE",
                    generated_at=result.scored_at,
                )
                .on_conflict_do_nothing(index_elements=["model_score_id"])
            )
            existing = await session.get(ModelExplanationModel, explanation_id)
            if existing is not None:
                return False
            await session.execute(statement)
            return True

    async def ingest_pulses(
        self, pulses: list[OTXPulse], fetched_at: datetime
    ) -> tuple[int, datetime | None]:
        accepted = 0
        watermark: datetime | None = None
        async with self._sessions() as session, session.begin():
            for pulse in pulses:
                watermark = max(watermark, pulse.modified) if watermark else pulse.modified
                for raw in pulse.indicators:
                    try:
                        provider = OTXIndicator.model_validate(raw)
                        canonical = normalize_indicator(provider.type, provider.indicator)
                    except (ValueError, TypeError):
                        continue
                    observation_id = uuid5(NAMESPACE_URL, f"otx:{provider.id}")
                    await session.execute(
                        insert(ThreatIndicatorModel)
                        .values(
                            indicator_id=canonical.indicator_id,
                            indicator_type=canonical.type.value,
                            normalized_value=canonical.value,
                            value_hash=canonical.value_hash,
                            active=True,
                            valid_from=provider.created,
                            valid_until=None,
                            fetched_at=fetched_at,
                            source="OTX",
                            severity="MEDIUM",
                            description=provider.description or pulse.description,
                            raw_json={},
                            first_seen=provider.created,
                            last_seen=provider.modified or provider.created,
                        )
                        .on_conflict_do_update(
                            index_elements=["indicator_id"],
                            set_={
                                "last_seen": provider.modified or provider.created,
                                "fetched_at": fetched_at,
                                "active": True,
                            },
                        )
                    )
                    existing_observation = await session.get(ThreatObservationModel, observation_id)
                    await session.execute(
                        insert(ThreatObservationModel)
                        .values(
                            observation_id=observation_id,
                            indicator_id=canonical.indicator_id,
                            provider="OTX",
                            provider_indicator_id=provider.id,
                            pulse_id=pulse.id,
                            tlp=pulse.TLP.upper(),
                            confidence=0.7,
                            description=(provider.description or pulse.description)[:4000],
                            tags_json=pulse.tags[:50],
                            raw_json={"id": provider.id, "type": provider.type},
                            observed_at=provider.modified or provider.created,
                            fetched_at=fetched_at,
                        )
                        .on_conflict_do_nothing(
                            index_elements=["provider", "provider_indicator_id"]
                        )
                    )
                    accepted += int(existing_observation is None)
                    await self._match_indicator(
                        session,
                        canonical.indicator_id,
                        observation_id,
                        canonical.type.value,
                        canonical.value,
                        fetched_at,
                    )
        return accepted, watermark

    async def backfill_recent_matches(
        self, *, since: datetime | None = None, limit: int = 1000
    ) -> int:
        """Reconcile matches for posts that arrived before their threat indicators."""
        created = 0
        async with self._sessions() as session, session.begin():
            query = (
                select(ThreatIndicatorModel, ThreatObservationModel)
                .join(ThreatObservationModel)
                .where(ThreatIndicatorModel.active.is_(True))
                .order_by(ThreatObservationModel.fetched_at.desc())
                .limit(limit)
            )
            if since is not None:
                query = query.where(ThreatObservationModel.fetched_at >= since)
            rows = (await session.execute(query)).all()
            for indicator, observation in rows:
                created += await self._match_indicator(
                    session,
                    indicator.indicator_id,
                    observation.observation_id,
                    indicator.indicator_type,
                    indicator.normalized_value,
                    observation.fetched_at,
                )
        return created

    async def _match_indicator(
        self,
        session: AsyncSession,
        indicator_id: str,
        observation_id: UUID,
        indicator_type: str,
        value: str,
        fetched_at: datetime,
    ) -> int:
        rows = await session.execute(self._candidate_post_query(indicator_type, value))
        created = 0
        for post, asset_id in rows:
            candidates = match_candidates(post.text, list(post.urls_json))
            if not any(
                kind.value == indicator_type and candidate == value
                for kind, candidate in candidates
            ):
                continue
            match_id = deterministic_match_id(
                post.scope_id, str(asset_id), post.post_id, observation_id
            )
            result = await session.execute(
                insert(ThreatMatchModel)
                .values(
                    match_id=match_id,
                    scope_id=post.scope_id,
                    asset_id=str(asset_id),
                    post_id=post.post_id,
                    indicator_id=indicator_id,
                    observation_id=observation_id,
                    match_type="EXACT",
                    matched_value=value,
                    event_time=post.event_time,
                    evidence_cutoff=max(post.event_time, fetched_at),
                    confidence=0.7,
                )
                .on_conflict_do_nothing(index_elements=["match_id"])
            )
            created += int(result.rowcount or 0)
        return created

    def _candidate_post_query(
        self, indicator_type: str, value: str
    ) -> Select[tuple[SocialPostModel, str | None]]:
        query = (
            select(SocialPostModel, PostAssetMentionModel.asset_id)
            .join(PostAssetMentionModel, PostAssetMentionModel.post_id == SocialPostModel.post_id)
            .where(PostAssetMentionModel.asset_id.is_not(None))
        )
        if indicator_type == "URL":
            return query.where(
                SocialPostModel.urls_json.contains([value])
                | SocialPostModel.text.ilike(f"%{value}%")
            )
        if indicator_type == "DOMAIN":
            return query.where(SocialPostModel.text.ilike(f"%{value}%"))
        if indicator_type in {"IPV4", "IPV6", "MD5", "SHA1", "SHA256", "EMAIL", "WALLET"}:
            return query.where(SocialPostModel.text.ilike(f"%{value}%"))
        return query.where(False)

    async def threat_context(
        self,
        scope_id: str,
        asset_id: str,
        cutoff: datetime,
        *,
        enabled: bool,
        freshness_seconds: int,
    ) -> ThreatContext:
        if not enabled:
            return ThreatContext(status=ThreatContextStatus.disabled, cutoff=cutoff)
        async with self._sessions() as session, session.begin():
            status = await session.get(ThreatFeedStatusModel, "OTX")
            if status is None or status.last_success_at is None:
                return ThreatContext(status=ThreatContextStatus.unavailable, cutoff=cutoff)
            if status.last_success_at < datetime.now(tz=UTC) - timedelta(seconds=freshness_seconds):
                return ThreatContext(status=ThreatContextStatus.stale, cutoff=cutoff)
            matches = list(
                await session.scalars(
                    select(ThreatMatchModel)
                    .join(ThreatObservationModel)
                    .where(
                        ThreatMatchModel.scope_id == scope_id,
                        ThreatMatchModel.asset_id == asset_id,
                        ThreatMatchModel.event_time <= cutoff,
                        ThreatObservationModel.fetched_at <= cutoff,
                    )
                    .order_by(ThreatMatchModel.event_time.desc())
                    .limit(20)
                )
            )

            match_ids = [str(item.match_id) for item in matches]
            snapshot_id = uuid5(
                NAMESPACE_URL,
                f"threat-context:{scope_id}:{asset_id}:{cutoff.isoformat()}:{','.join(sorted(match_ids))}",
            )
            context = ThreatContext(
                status=ThreatContextStatus.matched if matches else ThreatContextStatus.no_match,
                score=min(1.0, len(matches) / 3) if matches else None,
                confidence=max((item.confidence for item in matches), default=None),
                snapshot_id=str(snapshot_id),
                match_ids=match_ids,
                cutoff=cutoff,
            )
            await session.execute(
                insert(ThreatContextSnapshotModel)
                .values(
                    snapshot_id=snapshot_id,
                    scope_id=scope_id,
                    asset_id=asset_id,
                    cutoff=cutoff,
                    status=context.status.value,
                    score=context.score,
                    confidence=context.confidence,
                    match_ids_json=match_ids,
                    version=context.version,
                    generated_at=datetime.now(tz=UTC),
                )
                .on_conflict_do_nothing(index_elements=["snapshot_id"])
            )
            return context

    async def feed_modified_since(self) -> datetime | None:
        async with self._sessions() as session:
            row = await session.get(ThreatFeedStatusModel, "OTX")
            if row is None:
                return None
            value = row.checkpoint_json.get("modified_since")
            if not isinstance(value, str):
                return None
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    async def update_feed_status(
        self,
        *,
        status: str,
        checkpoint: dict[str, str] | None = None,
        fetched: int = 0,
        accepted: int = 0,
        error: str | None = None,
        success: bool = False,
        rate_limited_until: datetime | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        values = {
            "provider": "OTX",
            "status": status,
            "checkpoint_json": checkpoint or {},
            "last_attempt_at": now,
            "last_success_at": now if success else None,
            "rate_limited_until": rate_limited_until,
            "fetched_count": fetched,
            "accepted_count": accepted,
            "error_count": int(error is not None),
            "last_error": error,
            "updated_at": now,
        }
        update_values = {
            "status": status,
            "last_attempt_at": now,
            "rate_limited_until": rate_limited_until,
            "last_error": error,
            "updated_at": now,
        }
        if checkpoint is not None:
            update_values["checkpoint_json"] = checkpoint
        if success:
            update_values.update(
                {
                    "last_success_at": now,
                    "fetched_count": fetched,
                    "accepted_count": accepted,
                    "error_count": 0,
                }
            )
        elif error is not None:
            update_values["error_count"] = ThreatFeedStatusModel.error_count + 1
        async with self._sessions() as session, session.begin():
            await session.execute(
                insert(ThreatFeedStatusModel)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["provider"],
                    set_=update_values,
                )
            )
