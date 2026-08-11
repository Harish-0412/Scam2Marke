import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class PolicyProposal(BaseModel):
    name: str
    description: str
    generated_at: datetime | None = None
    approved: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ProposalResponse(BaseModel):
    proposal_id: str
    name: str
    description: str
    generated_at: datetime
    approved: bool
    details: dict[str, Any]


_policy_proposals: dict[str, ProposalResponse] = {}


@app.post("/v1/policy/propose", response_model=ProposalResponse)
async def propose_policy(proposal: PolicyProposal) -> ProposalResponse:
    proposal_id = str(uuid.uuid4())
    response = ProposalResponse(
        proposal_id=proposal_id,
        name=proposal.name,
        description=proposal.description,
        generated_at=proposal.generated_at or datetime.now(tz=UTC),
        approved=False,
        details=proposal.details,
    )
    _policy_proposals[proposal_id] = response
    return response


@app.post("/admin/policy/approve/{proposal_id}")
async def approve_policy(proposal_id: str) -> dict[str, str]:
    proposal = _policy_proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _policy_proposals[proposal_id] = proposal.model_copy(update={"approved": True})
    return {"status": "approved", "proposal_id": proposal_id}


@app.get("/v1/policy/proposals", response_model=list[ProposalResponse])
async def list_proposals() -> list[ProposalResponse]:
    return list(_policy_proposals.values())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
