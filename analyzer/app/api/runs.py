from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.api import AcceptedResponse, DashboardTestDataRequest, DialogRunRequest

router = APIRouter(
    prefix="/analysis/run",
    tags=["manual-runs"],
)


@router.post(
    path="/dialog",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
)
async def run_dialog(
    payload: DialogRunRequest,
    request: Request,
) -> AcceptedResponse:
    retried = await request.app.state.analysis_worker.retry(payload.call_id)
    if not retried:
        raise HTTPException(status_code=404, detail="Failed-задача не найдена")
    return AcceptedResponse()


@router.post("/dashboard", status_code=202, response_model=AcceptedResponse)
async def rebuild_dashboard(
    request: Request,
    snapshot_date: Annotated[date | None, Query(alias="date")] = None,
) -> AcceptedResponse:
    await request.app.state.dashboard_scheduler.rebuild(snapshot_date)
    return AcceptedResponse()


@router.post("/dashboard-test-data")
async def create_dashboard_test_data(
    request: Request,
    payload: DashboardTestDataRequest,
) -> dict:
    """Создаёт историю двух менеджеров и строит её production builder-ом."""
    service = request.app.state.dashboard_test_data
    if service is None:
        raise HTTPException(status_code=404, detail="Test data API is disabled")

    try:
        return await service.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
