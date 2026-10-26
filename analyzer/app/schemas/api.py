from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DialogRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    call_id: str = Field(min_length=1)
    manager_id: str

    @field_validator("manager_id")
    @classmethod
    def normalize_manager_id(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("manager_id должен содержать не больше восьми цифр")
        return value.zfill(8)


class PeriodRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    manager_id: str
    period_start: date
    period_end: date

    @field_validator("manager_id")
    @classmethod
    def normalize_manager_id(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("manager_id должен содержать не больше восьми цифр")
        return value.zfill(8)


class AcceptedResponse(BaseModel):
    status: str = "accepted"


class DialogCriterionResponse(BaseModel):
    code: str
    score: int
    recommendation: str


class DialogReportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    call_id: str = Field(alias="callId")
    status: str = "completed"
    q_score: float | None = Field(alias="qScore")
    results: list[DialogCriterionResponse]
    analyzers: dict
