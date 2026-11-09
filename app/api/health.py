from app.schemas.health import HealthResponse
from app.config import get_settings

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(service=get_settings().app_name)