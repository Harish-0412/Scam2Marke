from fastapi import APIRouter, Depends

from scam2market.api.routes import (
    analyst,
    auth,
    campaigns,
    evaluation,
    evidence,
    health,
    intelligence,
    model_governance,
    notifications,
    operations,
    surveillance,
    verification,
)
from scam2market.security.auth import authorize_api_request

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["authentication"])
protected = [Depends(authorize_api_request)]
api_router.include_router(surveillance.router, tags=["surveillance"], dependencies=protected)
api_router.include_router(campaigns.router, tags=["campaigns"], dependencies=protected)
api_router.include_router(
    evidence.router, tags=["evidence", "investigations"], dependencies=protected
)
api_router.include_router(
    evaluation.router, tags=["replays", "evaluation", "models"], dependencies=protected
)
api_router.include_router(analyst.router, tags=["analyst"], dependencies=protected)
api_router.include_router(operations.router, tags=["operations"], dependencies=protected)
api_router.include_router(notifications.router, tags=["notifications"], dependencies=protected)
api_router.include_router(
    model_governance.router, tags=["model governance", "feedback"], dependencies=protected
)
api_router.include_router(
    verification.router, tags=["official verification"], dependencies=protected
)
api_router.include_router(
    intelligence.router, tags=["intelligence", "explainability"], dependencies=protected
)
