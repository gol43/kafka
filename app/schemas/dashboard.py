from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MonthQScore(ApiModel):
    year: int
    month: int = Field(ge=1, le=12)
    q_score: int = Field(alias="qScore", ge=0, le=100)


class QScoreBlockResponse(ApiModel):
    personal: int = Field(ge=0, le=100)
    team_median: int = Field(alias="teamMedian", ge=0, le=100)
    months: list[MonthQScore]


class ClientRiskItem(ApiModel):
    client_epk: str = Field(alias="clientEpk")
    client_fio: str = Field(alias="clientFio")
    level: Literal["high", "medium", "low"]


class ClientRisksResponse(ApiModel):
    items: list[ClientRiskItem]


class CertainRiskItem(ApiModel):
    metric_code: str = Field(alias="metricCode")
    title: str
    level: Literal["high", "medium", "low"]
    quote: str
    count: int = Field(ge=1)
    recommendation: str


class CertainClientRiskResponse(ApiModel):
    client_epk: str = Field(alias="clientEpk")
    client_fio: str = Field(alias="clientFio")
    level: Literal["high", "medium", "low"]
    risks: list[CertainRiskItem]


class MetricCard(ApiModel):
    metric_code: str = Field(alias="metricCode")
    title: str
    percent1: int = Field(ge=0, le=100)
    percent2: int = Field(ge=0, le=100)
    delta: str


class MetricCardsResponse(ApiModel):
    items: list[MetricCard]


class MetricPeriod(ApiModel):
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    percent: int = Field(ge=0, le=100)


class MetricCommunication(ApiModel):
    call_id: str = Field(alias="callId")
    type: Literal["call"]
    client_epk: str = Field(alias="clientEpk")
    client_fio: str = Field(alias="clientFio")
    occurred_at: datetime = Field(alias="occurredAt")


class CertainImprovementMetricResponse(ApiModel):
    metric_code: str = Field(alias="metricCode")
    title: str
    recommendation: str
    severity: Literal["critical", "significant", "minor", "info"]
    periods: list[MetricPeriod]
    communications: list[MetricCommunication]


class DialogListItem(ApiModel):
    call_id: str = Field(alias="callId")
    type: Literal["call"]
    client_epk: str = Field(alias="clientEpk")
    client_fio: str = Field(alias="clientFio")
    occurred_at: datetime = Field(alias="occurredAt")
    score: int = Field(ge=0, le=100)


class DialogsListResponse(ApiModel):
    items: list[DialogListItem]
    has_more: bool = Field(alias="hasMore")


class DialogRisk(ApiModel):
    code: str
    title: str
    severity: Literal["high", "medium", "low"]


class DialogImprovement(ApiModel):
    code: str
    title: str
    severity: Literal["critical", "significant", "minor", "info"]
    recommendation: str
    quote: str


class DialogReportResponse(ApiModel):
    call_id: str = Field(alias="callId")
    client_epk: str = Field(alias="clientEpk")
    client_fio: str = Field(default="", alias="clientFio")
    occurred_at: datetime = Field(alias="occurredAt")
    type: Literal["call"]
    score: int = Field(ge=0, le=100)
    deviations_count: int = Field(alias="deviationsCount", ge=0)
    risks: list[DialogRisk]
    strengths: str
    improvements: list[DialogImprovement]
