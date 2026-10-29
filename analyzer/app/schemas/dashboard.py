from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QScoreBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    personal: float
    team_median: float = Field(alias="teamMedian")
    communications_count: int = Field(alias="communicationsCount")
    months: list[dict]


class ItemsBlockResponse(BaseModel):
    items: list[dict]


class DialogListItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    call_id: str = Field(alias="callId")
    type: str
    client_epk: str = Field(alias="clientEpk")
    occurred_at: datetime = Field(alias="occurredAt")
    score: float


class DialogReportResponse(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    call_id: str = Field(alias="callId")
    client_epk: str = Field(alias="clientEpk")
    occurred_at: datetime = Field(alias="occurredAt")
    type: str
    score: float
    deviations_count: int = Field(alias="deviationsCount")
