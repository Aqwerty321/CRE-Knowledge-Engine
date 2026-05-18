from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.slack import router as slack_router


api_router = APIRouter()
api_router.include_router(health_router, prefix="/health")
api_router.include_router(slack_router, prefix="/slack")
