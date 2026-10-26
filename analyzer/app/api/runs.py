from fastapi import APIRouter, Request, status

from datetime import date
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
    await request.app.state.analysis_worker.enqueue(
        "dialog",
        payload.call_id,
        payload.manager_id,
    )
    return AcceptedResponse()


@router.post("/dashboard", status_code=202, response_model=AcceptedResponse)
async def rebuild_dashboard(
    request: Request,
    snapshot_date: Annotated[date | None, Query(alias="date")] = None,
) -> AcceptedResponse:
    await request.app.state.dashboard_scheduler.rebuild(snapshot_date)
    return AcceptedResponse()
