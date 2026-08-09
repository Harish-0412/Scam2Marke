from scam2market.campaigns.policy import CampaignStateMachine
from scam2market.campaigns.repository import CampaignRepository
from scam2market.campaigns.schemas import CampaignEvidence, CampaignUpdate
from scam2market.intelligence.fusion import FusionResult
from scam2market.schemas.events import CanonicalEvent, EventType


class CampaignService:
    def __init__(
        self,
        repository: CampaignRepository,
        state_machine: CampaignStateMachine | None = None,
    ) -> None:
        self._repository = repository
        self._state_machine = state_machine or CampaignStateMachine()

    async def process(self, event: CanonicalEvent) -> CampaignUpdate:
        if event.event_type != EventType.model_fusion_scored:
            raise ValueError("campaign service only accepts fusion score events")
        return await self._repository.apply(
            CampaignEvidence(
                event_id=event.event_id,
                correlation_id=event.trace.correlation_id,
                causation_id=event.trace.causation_id,
                event_time=event.event_time,
                fusion=FusionResult.model_validate(event.payload),
            ),
            self._state_machine,
        )
