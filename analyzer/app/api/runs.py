from fastapi import APIRouter, HTTPException, Request, status

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Query

from app.schemas.api import AcceptedResponse, DialogRunRequest

router = APIRouter(
    prefix="/analysis/run",
    tags=["manual-runs"],
)


@router.post(
    "/dialog",
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
    end_date: Annotated[date | None, Query(alias="date")] = None,
    days: Annotated[int | None, Query(ge=5, le=183)] = None,
) -> dict:
    """Создаёт историю двух менеджеров и строит её production builder-ом."""

    service = request.app.state.dashboard_test_data
    if service is None:
        raise HTTPException(status_code=404, detail="Test data API is disabled")

    settings = request.app.state.settings
    return await service.create(
        end_date=end_date or datetime.now(UTC).date(),
        days=days or settings.test_data_default_days,
    )
