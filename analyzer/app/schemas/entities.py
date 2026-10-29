import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DialogEntity(BaseModel):
    """Диалог, ожидающий полного анализа."""

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    manager_id: str
    client_epk: str
    work_date: date
    occurred_at: datetime
    received_at: datetime
    duration_seconds: int
    cleaned_text: str
    required_analyzers: list[str] = Field(default_factory=list)
    criteria_version: str
    prompt_version: str
    model_name: str
    created_at: datetime


class AnalysisTaskEntity(BaseModel):
    """Задание, которое worker забрал из PostgreSQL."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: str
    attempt_count: int = 0


class DialogReportEntity(BaseModel):
    """Полный завершённый отчёт одного звонка."""

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    manager_id: str
    client_epk: str
    work_date: date
    occurred_at: datetime
    cleaned_text: str
    hygiene_results: list[dict] = Field(default_factory=list)
    deposit_results: list[dict] = Field(default_factory=list)
    risk_results: list[dict] = Field(default_factory=list)
    audio_results: dict = Field(default_factory=dict)
    factor_results: dict = Field(default_factory=dict)
    general_score: float
    deposit_score: float | None = None
    score: float
    deposit_topic: bool
    critical_violation: bool
    deviations_count: int
    risks_count: int
    report_payload: dict = Field(default_factory=dict)
    completed_at: datetime
