from fastapi import APIRouter, HTTPException, Request

from app.exceptions import EntityNotFoundError
from app.schemas.dashboard import (
    DialogReportResponse,
    ItemsBlockResponse,
    QScoreBlockResponse,
)

router = APIRouter(
    prefix="/manager",
    tags=["manager"],
)


def normalize_manager_id(value: str) -> str:
    if not value.isdigit() or len(value) > 8:
        raise HTTPException(
            status_code=400,
            detail="manager_id должен содержать не больше восьми цифр",
        )
    return value.zfill(8)


async def _block(request: Request, manager_id: str, name: str):
    try:
        return await request.app.state.manager_service.dashboard_block(
            normalize_manager_id(manager_id),
            name,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/q-score", response_model=QScoreBlockResponse)
async def get_q_score(manager_id: str, request: Request):
    return await _block(request, manager_id, "qScore")


@router.get("/{manager_id}/clients-at-risk", response_model=ItemsBlockResponse)
async def get_clients_at_risk(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, "clientsAtRisk")}


@router.get("/{manager_id}/strengths", response_model=ItemsBlockResponse)
async def get_strengths(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, "strengths")}


@router.get("/{manager_id}/improvements", response_model=ItemsBlockResponse)
async def get_improvements(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, "improvements")}


@router.get("/{manager_id}/communications", response_model=ItemsBlockResponse)
async def get_communications(manager_id: str, request: Request):
    return {"items": await _block(request, manager_id, "communications")}


@router.get("/{manager_id}/clients/{client_epk}/metrics/{metric_code}")
async def get_client_metric(
    manager_id: str,
    client_epk: str,
    metric_code: str,
    request: Request,
):
    try:
        return await request.app.state.manager_service.client_metric(
            normalize_manager_id(manager_id),
            client_epk,
            metric_code,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{manager_id}/metrics/{metric_code}")
async def get_metric_detail(manager_id: str, metric_code: str, request: Request):
    try:
        return await request.app.state.manager_service.metric_detail(
            normalize_manager_id(manager_id),
            metric_code,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dialogs/{call_id}", response_model=DialogReportResponse)
async def get_dialog_report(
    call_id: str,
    request: Request,
) -> DialogReportResponse:
    try:
        result = await request.app.state.manager_service.dialog_report(call_id)
        return DialogReportResponse.model_validate(result)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
