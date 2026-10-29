from datetime import date as Date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.exceptions import EntityNotFoundError
from app.schemas.dashboard import (
    DialogListItem,
    DialogReportResponse,
    ItemsBlockResponse,
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


async def _block(request: Request, manager_id: str, report_date: Date, name: str):
    try:
        return await request.app.state.manager_service.dashboard_block(
            normalize_manager_id(manager_id),
            report_date,
            name,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/q-score", response_model=QScoreBlockResponse)
async def get_q_score(manager_id: str, date: Date, request: Request):
    return await _block(request, manager_id, date, "q_score_block")


@router.get("/{manager_id}/client-risks", response_model=ItemsBlockResponse)
async def get_client_risks(manager_id: str, date: Date, request: Request):
    return {"items": await _block(request, manager_id, date, "client_risks_block")}


@router.get("/{manager_id}/client-risks/{client_epk}")
async def get_client_risk(
    manager_id: str,
    client_epk: str,
    date: Date,
    request: Request,
):
    try:
        return await request.app.state.manager_service.client_risk(
            normalize_manager_id(manager_id),
            date,
            client_epk,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/strengths", response_model=ItemsBlockResponse)
async def get_strengths(manager_id: str, date: Date, request: Request):
    return {"items": await _block(request, manager_id, date, "strengths_block")}


@router.get("/{manager_id}/improvements", response_model=ItemsBlockResponse)
async def get_improvements(manager_id: str, date: Date, request: Request):
    return {"items": await _block(request, manager_id, date, "improvements_block")}


@router.get("/{manager_id}/improvements/{metric_code}")
async def get_improvement(
    manager_id: str,
    metric_code: str,
    date: Date,
    request: Request,
):
    try:
        return await request.app.state.manager_service.improvement(
            normalize_manager_id(manager_id),
            date,
            metric_code,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/dialogs", response_model=list[DialogListItem])
async def get_dialogs(
    manager_id: str,
    date: Date,
    request: Request,
    client_epk: str | None = None,
    date_from: Date | None = None,
    date_to: Date | None = None,
    type: Literal["call"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
):
    del type
    return await request.app.state.manager_service.dialogs(
        manager_id=normalize_manager_id(manager_id),
        report_date=date,
        limit=limit,
        client_epk=client_epk,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/dialogs/{call_id}", response_model=DialogReportResponse)
async def get_dialog_report(call_id: str, request: Request):
    try:
        return await request.app.state.manager_service.dialog_report(call_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
