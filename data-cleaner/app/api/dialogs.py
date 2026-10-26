import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.metrics import CLEANER_ACCEPTED
from app.schemas.dialogs import CleanerRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/v1/dialogs",
    tags=["internal"],
)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def accept_dialog(payload: CleanerRequest, request: Request) -> Response:
    logger.info("Cleaner dialog received call_id=%s", payload.call_id)
    try:
        await request.app.state.dialog_service.accept(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    CLEANER_ACCEPTED.inc()
    return Response(status_code=status.HTTP_202_ACCEPTED)
