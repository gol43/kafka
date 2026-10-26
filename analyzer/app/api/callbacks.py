import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.metrics import ANALYZER_CALLBACKS
from app.schemas.dialogs import CleanedDialog

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/v1/dialogs",
    tags=["internal"],
)


@router.post("/cleaned", status_code=status.HTTP_202_ACCEPTED)
async def cleaned_dialog(payload: CleanedDialog, request: Request) -> Response:
    logger.info("Dialog callback received call_id=%s", payload.call_id)
    try:
        outcome = await request.app.state.dialog_intake.accept(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ANALYZER_CALLBACKS.labels(outcome=outcome).inc()
    return Response(status_code=status.HTTP_202_ACCEPTED)
