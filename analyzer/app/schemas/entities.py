import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DialogEntity(BaseModel):
    """Доменное представление диалога без зависимости от SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    manager_id: str
    client_epk: str = ""
    client_fio: str = ""
    work_date: date
    occurred_at: datetime | None = None
    duration_seconds: int = 0
    cleaned_text: str
    dialog_data: list[dict] = Field(default_factory=list)
    required_analyzers: list[str] = Field(default_factory=list)
    analysis_results: dict = Field(default_factory=dict)
    q_score: float | None = None
    general_score: float | None = None
    deposit_topic: bool = False
    deposit_score: float | None = None
    deviations_count: int = 0
    dialog_report: dict = Field(default_factory=dict)
    daily_report_id: uuid.UUID | None = None
    created_at: datetime


class AnalysisTaskEntity(BaseModel):
    """Задание, которое бизнес-логика получила из внутренней очереди."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    entity_key: str
    manager_id: str
    payload: dict = Field(default_factory=dict)


class AggregateReportEntity(BaseModel):
    """Единое доменное чтение одной из четырёх таблиц отчётов."""

    id: uuid.UUID
    report_type: str
    manager_id: str
    period_start: date
    period_end: date
    q_score: float | None = None
    score_sum: float | None = None
    communications_count: int
    summary: str | None = None
    details: dict = Field(default_factory=dict)
