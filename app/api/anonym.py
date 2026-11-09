from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.anonym import AnonymizationRequest, AnonymizationResponse


router = APIRouter(prefix="/anonymize", tags=["anonymize"])


@router.post("", response_model=AnonymizationResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_anonymization(payload: AnonymizationRequest, request: Request):
    try:
        await request.app.state.data_cleaner_service.save_dialog(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AnonymizationResponse()


async def anonymization_validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})
