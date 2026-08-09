from fastapi import APIRouter

from scam2market.api.routes import campaigns, health, surveillance

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(surveillance.router, tags=["surveillance"])
api_router.include_router(campaigns.router, tags=["campaigns"])
