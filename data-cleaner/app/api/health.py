from fastapi import APIRouter, HTTPException

from app.database.connection import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    if not await check_database():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
