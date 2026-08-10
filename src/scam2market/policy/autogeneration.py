from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import datetime

app = FastAPI()

# In‑memory store for demo – replace with persistent DB table `policy_proposals`
_policy_proposals: Dict[str, Dict[str, Any]] = {}


class PolicyProposal(BaseModel):
    name: str
    description: str
    generated_at: datetime.datetime = None
    approved: bool = False
    details: Dict[str, Any] = {}


class ProposalResponse(BaseModel):
    proposal_id: str
    name: str
    description: str
    generated_at: datetime.datetime
    approved: bool
    details: Dict[str, Any]


@app.post("/v1/policy/propose", response_model=ProposalResponse)
async def propose_policy(proposal: PolicyProposal):
    proposal_id = str(uuid.uuid4())
    generated_at = datetime.datetime.utcnow()
    data = proposal.dict()
    data.update({"proposal_id": proposal_id, "generated_at": generated_at, "approved": False})
    _policy_proposals[proposal_id] = data
    return ProposalResponse(**data)


@app.post("/admin/policy/approve/{proposal_id}")
async def approve_policy(proposal_id: str):
    if proposal_id not in _policy_proposals:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _policy_proposals[proposal_id]["approved"] = True
    return {"status": "approved", "proposal_id": proposal_id}


@app.get("/v1/policy/proposals", response_model=List[ProposalResponse])
async def list_proposals():
    return [ProposalResponse(**p) for p in _policy_proposals.values()]


@app.get("/health")
async def health():
    return {"status": "ok"}
