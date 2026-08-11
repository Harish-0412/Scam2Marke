from fastapi import APIRouter

from scam2market.api.routes import (
    analyst,
    campaigns,
    evaluation,
    evidence,
    health,
    operations,
    surveillance,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(surveillance.router, tags=["surveillance"])
api_router.include_router(campaigns.router, tags=["campaigns"])
api_router.include_router(evidence.router, tags=["evidence", "investigations"])
api_router.include_router(evaluation.router, tags=["replays", "evaluation", "models"])
api_router.include_router(analyst.router, tags=["analyst"])
api_router.include_router(operations.router, tags=["operations"])
