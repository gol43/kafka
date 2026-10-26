from pydantic import BaseModel, ConfigDict, Field


class QScoreBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    personal: float
    team_median: float = Field(alias="teamMedian")
    communications_count: int = Field(alias="communicationsCount")
    low_score_share: float = Field(alias="lowScoreShare")
    months: list[dict]


class ItemsBlockResponse(BaseModel):
    items: list[dict]


class DialogReportResponse(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    call_id: str = Field(alias="callId")
    client_fio: str = Field(alias="clientFio")
    score: float
    deviations_count: int = Field(alias="deviationsCount")
