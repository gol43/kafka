from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.exceptions import EntityNotFoundError
from app.schemas.dashboard import (
    CertainClientRiskResponse,
    CertainImprovementMetricResponse,
    ClientRisksResponse,
    DialogReportResponse,
    DialogsListResponse,
    MetricCardsResponse,
    QScoreBlockResponse,
)

router = APIRouter(prefix="/manager", tags=["manager"])


def normalize_manager_id(value: str) -> str:
    if not value.isdigit() or len(value) > 8:
        raise HTTPException(
            status_code=400,
            detail="manager_id должен содержать не больше восьми цифр",
        )
    return value.zfill(8)


async def _block(
    request: Request,
    manager_id: str,
    name: str,
):
    try:
        return await request.app.state.manager_service.dashboard_block(
            normalize_manager_id(manager_id),
            name,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/q-score", response_model=QScoreBlockResponse)
async def get_q_score(manager_id: str, request: Request):
    return await _block(request, manager_id, name="q_score")


@router.get("/{manager_id}/client-risks", response_model=ClientRisksResponse)
async def get_client_risks(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, name="risks")}


@router.get(
    "/{manager_id}/client-risks/{client_epk}",
    response_model=CertainClientRiskResponse,
)
async def get_certain_client_risk(
    manager_id: str,
    client_epk: str,
    request: Request,
):
    try:
        return await request.app.state.manager_service.certain_client_risk(
            normalize_manager_id(manager_id),
            client_epk,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/strengths", response_model=MetricCardsResponse)
async def get_strengths(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, name="strengths")}


@router.get("/{manager_id}/improvements", response_model=MetricCardsResponse)
async def get_improvements(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, name="improvements")}


@router.get(
    "/{manager_id}/improvements/{metric_code}",
    response_model=CertainImprovementMetricResponse,
)
async def get_certain_improvement_metric(
    manager_id: str,
    metric_code: str,
    request: Request,
):
    try:
        return await request.app.state.manager_service.certain_improvement_metric(
            normalize_manager_id(manager_id),
            metric_code,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/dialogs", response_model=DialogsListResponse)
async def get_dialogs(
    manager_id: str,
    request: Request,
    score: Literal["low", "medium", "high"] | None = None,
    client_epk: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
):
    settings = request.app.state.settings
    if limit is None:
        limit = settings.latest_communications_limit
    if limit > settings.communications_max_limit:
        raise HTTPException(
            status_code=400,
            detail="limit превышает максимальное значение",
        )

    return await request.app.state.manager_service.dialogs(
        manager_id=normalize_manager_id(manager_id),
        score=score,
        client_epk=client_epk,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.get("/dialogs/{call_id}", response_model=DialogReportResponse)
async def get_dialog_report(call_id: str, request: Request):
    try:
        return await request.app.state.manager_service.dialog_report(call_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
